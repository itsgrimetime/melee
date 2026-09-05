"""Standalone utility functions for worktree-doctor checks."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path


def detect_repo_root(cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        root = result.stdout.strip()
        if root:
            return Path(root).resolve()
    return Path(__file__).absolute().parent.parent


# Compute once at import time; __init__.py imports this symbol.
ROOT = detect_repo_root()


MACHO_CPU_TYPES = {
    0x01000007: "x86_64",
    0x0100000C: "arm64",
}


def install_base_dol(candidate: Path, dol_path: Path) -> str:
    if dol_path.is_symlink() and not dol_path.exists():
        dol_path.unlink()

    dol_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dol_path.symlink_to(candidate)
        return "linked"
    except OSError:
        shutil.copy2(candidate, dol_path)
        return "copied"


def detect_macho_arch(path: Path) -> str | None:
    try:
        data = path.read_bytes()[:4096]
    except OSError:
        return None
    if len(data) < 8:
        return None

    magic = data[:4]
    if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        endian = "<"
        cpu_type_offset = 4
    elif magic in (b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        endian = ">"
        cpu_type_offset = 4
    elif magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        if len(data) < 8:
            return None
        nfat_arch = struct.unpack(">I", data[4:8])[0]
        arches = set()
        offset = 8
        entry_size = 20
        for _ in range(nfat_arch):
            if len(data) < offset + entry_size:
                break
            cpu_type = struct.unpack(">I", data[offset : offset + 4])[0]
            arch = MACHO_CPU_TYPES.get(cpu_type)
            if arch:
                arches.add(arch)
            offset += entry_size
        if "x86_64" in arches and "arm64" in arches:
            return "universal"
        if len(arches) == 1:
            return next(iter(arches))
        return None
    else:
        return None

    if len(data) < cpu_type_offset + 4:
        return None
    cpu_type = struct.unpack(
        endian + "I",
        data[cpu_type_offset : cpu_type_offset + 4],
    )[0]
    return MACHO_CPU_TYPES.get(cpu_type)


def redownload_dtk(dtk: Path, dtk_download_tag: str = "v1.8.3") -> bool:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64") or sys.platform == "darwin":
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "aarch64"
    elif machine in ("i686", "i386"):
        arch = "i686"
    else:
        arch = machine

    if sys.platform == "darwin":
        system = "macos"
        suffix = ""
    elif sys.platform.startswith("linux"):
        system = "linux"
        suffix = ""
    elif sys.platform.startswith(("win32", "cygwin")):
        system = "windows"
        arch = "x86_64"
        suffix = ".exe"
    else:
        return False

    asset = f"dtk-{system}-{arch}{suffix}"
    url = f"https://github.com/encounter/decomp-toolkit/releases/download/{dtk_download_tag}/{asset}"

    try:
        dtk.unlink()
    except OSError:
        pass
    dtk.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            with open(dtk, "wb") as f:
                shutil.copyfileobj(response, f)
    except (urllib.error.URLError, OSError):
        return False
    dtk.chmod(dtk.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return dtk.exists() and dtk.stat().st_size > 0


def _terminate_process_group(proc: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        return proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        return proc.communicate()


def run_cmd(
    args: list[str],
    timeout: float,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_message: str = "timed out",
) -> subprocess.CompletedProcess[str]:
    cwd = cwd or ROOT
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _terminate_process_group(proc)
        timeout_detail = timeout_message
        if stderr:
            timeout_detail = f"{stderr.rstrip()}\n{timeout_message}"
        return subprocess.CompletedProcess(
            args,
            124,
            stdout or exc.stdout or "",
            timeout_detail,
        )


def run_git(args: list[str], allow_fail: bool = False) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0 and not allow_fail:
        raise RuntimeError(result.stderr.strip())
    return result.stdout if result.returncode == 0 else ""


def _git_for_root(root: Path, args: list[str], allow_fail: bool = False) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0 and not allow_fail:
        raise RuntimeError(result.stderr.strip())
    return result.stdout if result.returncode == 0 else ""


def build_table_typer(root: Path) -> subprocess.CompletedProcess[str]:
    table_typer_dir = root / "tools" / "table-typer"
    try:
        return subprocess.run(
            ["go", "build", "-o", "table-typer", "."],
            cwd=table_typer_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(["go", "build"], 124, exc.stdout or "", exc.stderr or "timed out")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(["go", "build"], 127, "", str(exc))


def refresh_report_json(root: Path) -> subprocess.CompletedProcess[str]:
    """Refresh build/GALE01/report.json via configure.py + ninja.

    Uses the module-level REPORT_REFRESH_TIMEOUT_SECONDS so tests can
    monkeypatch it.
    """
    from . import REPORT_REFRESH_TIMEOUT_SECONDS

    configure = subprocess.run([sys.executable, "configure.py"], cwd=root, capture_output=True, text=True)
    if configure.returncode != 0:
        return configure

    report_rel = Path("build") / "GALE01" / "report.json"
    cmd = ["ninja", str(report_rel)]
    return run_cmd(
        cmd,
        timeout=REPORT_REFRESH_TIMEOUT_SECONDS,
        cwd=root,
        timeout_message=(
            f"timed out after {REPORT_REFRESH_TIMEOUT_SECONDS}s running "
            f"{shlex.join(cmd)}; killed the build process group"
        ),
    )


def read_from_master_with_mode(
    rel_path: str, root: Path | None = None
) -> tuple[bytes, int] | None:
    """Read a regular master file and its Git executable mode."""
    root = root or ROOT
    tree = subprocess.run(
        ["git", "ls-tree", "master", "--", rel_path],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if tree.returncode != 0 or not tree.stdout.strip():
        return None
    mode_text = tree.stdout.split(maxsplit=1)[0]
    mode = {"100644": 0o644, "100755": 0o755}.get(mode_text)
    if mode is None:
        return None

    content = subprocess.run(
        ["git", "show", f"master:{rel_path}"],
        cwd=root,
        capture_output=True,
        text=False,
    )
    if content.returncode != 0:
        return None
    return content.stdout, mode


def _safe_destination_parent(dest: Path, root: Path, *, create: bool) -> bool:
    root = root.absolute()
    dest = dest.absolute()
    try:
        relative = dest.relative_to(root)
    except ValueError:
        return False
    if not relative.parts:
        return False

    try:
        root_stat = root.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        return False

    current = root
    for component in relative.parts[:-1]:
        current /= component
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            if not create:
                continue
            try:
                current.mkdir()
                current_stat = current.lstat()
            except OSError:
                return False
        except OSError:
            return False
        if not stat.S_ISDIR(current_stat.st_mode) or stat.S_ISLNK(
            current_stat.st_mode
        ):
            return False
    return True


def _read_regular_file_no_follow(path: Path) -> tuple[bytes, int] | None:
    try:
        path_stat = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(path_stat.st_mode):
        return None

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_dev != path_stat.st_dev
            or opened_stat.st_ino != path_stat.st_ino
        ):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return content, stat.S_IMODE(path_stat.st_mode)


def read_tooling_file_with_mode(
    path: Path, root: Path
) -> tuple[bytes, int] | None:
    """Read a regular tooling file without following it or parent symlinks."""
    if not _safe_destination_parent(path, root, create=False):
        return None
    return _read_regular_file_no_follow(path)


def _stage_bytes(dest: Path, content: bytes, mode: int, purpose: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{dest.name}.{purpose}.", dir=dest.parent
    )
    staged = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        staged.chmod(mode)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _stage_symlink(dest: Path, target: str, purpose: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{dest.name}.{purpose}.", dir=dest.parent
    )
    os.close(fd)
    staged = Path(raw_path)
    try:
        staged.unlink()
        staged.symlink_to(target)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _snapshot_destination(path: Path) -> tuple[str, bytes | str, int] | None:
    if not os.path.lexists(path):
        return None
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect tooling destination: {path}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        return "symlink", os.readlink(path), 0
    regular = _read_regular_file_no_follow(path)
    if regular is None:
        raise ValueError(f"tooling destination is not a regular file: {path}")
    return "regular", regular[0], regular[1]


def _restore_master_entries(
    entries: list[tuple[Path, bytes, int]], root: Path
) -> bool:
    snapshots: dict[Path, tuple[str, bytes | str, int] | None] = {}
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        if not all(
            _safe_destination_parent(dest, root, create=False)
            for dest, _content, _mode in entries
        ):
            return False
        for dest, _content, _mode in entries:
            snapshots[dest] = _snapshot_destination(dest)

        if not all(
            _safe_destination_parent(dest, root, create=True)
            for dest, _content, _mode in entries
        ):
            return False

        for dest, content, mode in entries:
            staged[dest] = _stage_bytes(dest, content, mode, "restore")
            snapshot = snapshots[dest]
            if snapshot is not None:
                kind, old_content, old_mode = snapshot
                if kind == "regular":
                    assert isinstance(old_content, bytes)
                    backups[dest] = _stage_bytes(
                        dest, old_content, old_mode, "rollback"
                    )
                else:
                    assert isinstance(old_content, str)
                    backups[dest] = _stage_symlink(
                        dest, old_content, "rollback"
                    )

        for dest, _content, _mode in entries:
            if not _safe_destination_parent(dest, root, create=False):
                raise ValueError(f"unsafe tooling destination parent: {dest}")
            os.replace(staged[dest], dest)
            replaced.append(dest)
    except (OSError, ValueError):
        rollback_ok = True
        for dest in reversed(replaced):
            try:
                if not _safe_destination_parent(dest, root, create=False):
                    rollback_ok = False
                    continue
                backup = backups.get(dest)
                if backup is None:
                    dest.unlink(missing_ok=True)
                else:
                    os.replace(backup, dest)
            except OSError:
                rollback_ok = False
        if not rollback_ok:
            return False
        return False
    finally:
        for temporary in (*staged.values(), *backups.values()):
            temporary.unlink(missing_ok=True)
    return True


def restore_group_from_master(rel_paths: tuple[str, ...], root: Path) -> bool:
    """Restore a tooling group from master, rolling back partial replacement."""
    entries: list[tuple[Path, bytes, int]] = []
    for rel_path in rel_paths:
        master_file = read_from_master_with_mode(rel_path, root)
        if master_file is None:
            return False
        content, mode = master_file
        entries.append((root / rel_path, content, mode))
    return _restore_master_entries(entries, root)


def restore_from_master(rel_path: str, dest: Path) -> bool:
    master_file = read_from_master_with_mode(rel_path, ROOT)
    if master_file is None:
        return False
    content, mode = master_file
    return _restore_master_entries([(dest, content, mode)], ROOT)


def read_from_master(rel_path: str) -> bytes | None:
    master_file = read_from_master_with_mode(rel_path, ROOT)
    if master_file is None:
        return None
    return master_file[0]


def matches_master(rel_path: str, path: Path) -> bool | None:
    master_file = read_from_master_with_mode(rel_path, ROOT)
    if master_file is None:
        return None
    expected, expected_mode = master_file
    current_file = read_tooling_file_with_mode(path, ROOT)
    if current_file is None:
        return False
    actual, actual_mode = current_file
    return actual == expected and actual_mode == expected_mode


def has_worktree_changes(rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", rel_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


# ── Ghidra detection ─────────────────────────────────────────────────────────
# Mirrors tools/melee-agent/src/cli/ghidra/detect.py so worktree-doctor can
# validate Ghidra availability without depending on melee-agent being importable.

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


def resolve_melee_agent_module_path(executable: Path) -> Path | None:
    launcher_probe = run_cmd(
        [str(executable)],
        timeout=10,
        env={**os.environ, "MELEE_AGENT_PRINT_SRC_CLI": "1"},
    )
    if launcher_probe.returncode == 0:
        probed_path = _first_absolute_path_line(launcher_probe.stdout)
        if probed_path is not None:
            return probed_path

    interpreter = sys.executable
    try:
        first_line = executable.read_text(errors="ignore").splitlines()[0]
    except (OSError, IndexError):
        first_line = ""
    if first_line.startswith("#!") and "python" in first_line.lower():
        interpreter = first_line[2:].strip().split()[0]

    result = run_cmd(
        [
            interpreter,
            "-c",
            "import pathlib, src.cli; print(pathlib.Path(src.cli.__file__).resolve())",
        ],
        timeout=10,
    )
    if result.returncode != 0:
        return None
    text = result.stdout.strip().splitlines()
    if not text:
        return None
    return Path(text[-1])


def _first_absolute_path_line(stdout: str) -> Path | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text:
            continue
        path = Path(text)
        if path.is_absolute():
            return path
    return None


def entrypoint_uses_worktree_launcher(executable: Path) -> bool:
    try:
        text = executable.read_text(errors="ignore")
    except OSError:
        return False
    return "src.launcher" in text


def is_stale_melee_agent_entrypoint(result) -> bool:
    """Return True if a CheckResult indicates the melee-agent entrypoint is stale."""
    return (
        result.level == "warn"
        and (
            (
                "melee-agent imports src.cli from" in result.message
                and "expected" in result.message
            )
            or "does not use the worktree-resolving launcher" in result.message
        )
    )


def reinstall_repo_melee_agent(root: Path) -> subprocess.CompletedProcess[str]:
    return run_cmd([sys.executable, "-m", "pip", "install", "-e", "tools/melee-agent"], timeout=120)


_GLOBAL_MELEE_AGENT_INSTALL_FIX = (
    "refresh the global editable install from the authoritative shared checkout "
    "(the master/shared checkout, not a matcher worktree): "
    "python -m pip install -e /path/to/melee/tools/melee-agent; "
    "do not run pip install -e from matcher worktrees"
)


def _dist_name(dist) -> str:
    try:
        return str(dist.metadata.get("Name") or "").strip()
    except Exception:
        return ""


def _dist_location(dist) -> str:
    try:
        return str(dist.locate_file(""))
    except Exception:
        return "<unknown-location>"


def _dist_exposes_melee_agent(dist) -> bool:
    for entry_point in getattr(dist, "entry_points", ()) or ():
        if (
            getattr(entry_point, "group", None) == "console_scripts"
            and getattr(entry_point, "name", None) == "melee-agent"
        ):
            return True
    return False


def collect_melee_agent_distribution_warnings(distributions=None) -> list:
    from .doctor import CheckResult

    providers = []
    for dist in distributions if distributions is not None else metadata.distributions():
        name = _dist_name(dist)
        if not name:
            continue
        normalized = name.replace("_", "-").lower()
        if normalized in {"melee-agent", "melee-decomp-agent"} or _dist_exposes_melee_agent(dist):
            providers.append(dist)

    unique: dict[tuple[str, str], object] = {}
    for dist in providers:
        name = _dist_name(dist)
        version = str(getattr(dist, "version", "") or "<unknown-version>")
        unique[(name.lower(), version, _dist_location(dist))] = dist
    providers = sorted(unique.values(), key=lambda dist: (_dist_name(dist).lower(), _dist_location(dist)))

    if len(providers) <= 1:
        return []

    details = "; ".join(
        f"{_dist_name(dist)} {getattr(dist, 'version', '<unknown-version>')} at {_dist_location(dist)}"
        for dist in providers
    )
    return [
        CheckResult(
            "warn",
            f"multiple installed melee-agent distributions can affect the global CLI: {details}",
            _GLOBAL_MELEE_AGENT_INSTALL_FIX,
        )
    ]


def collect_melee_agent_entrypoint_warnings(
    root: Path,
    executable: Path,
    module_path: Path | None = None,
) -> list:
    from .doctor import CheckResult

    expected = (root / "tools" / "melee-agent" / "src" / "cli" / "__init__.py").resolve()
    actual = module_path.resolve() if module_path is not None else resolve_melee_agent_module_path(executable)
    if actual is None:
        return [
            CheckResult(
                "warn",
                f"could not determine src.cli import path for {executable}",
                _GLOBAL_MELEE_AGENT_INSTALL_FIX,
            )
        ]
    if actual == expected:
        if not entrypoint_uses_worktree_launcher(executable):
            return [
                CheckResult(
                    "warn",
                    "melee-agent imports repo-local src.cli but does not use the worktree-resolving launcher",
                    _GLOBAL_MELEE_AGENT_INSTALL_FIX,
                )
            ]
        return [CheckResult("ok", f"melee-agent imports repo-local src.cli: {actual}")]
    if entrypoint_uses_worktree_launcher(executable):
        return [CheckResult("ok", f"melee-agent imports installed src.cli: {actual}")]
    return [
        CheckResult(
            "warn",
            f"melee-agent imports src.cli from {actual}, expected {expected}",
            _GLOBAL_MELEE_AGENT_INSTALL_FIX,
        )
    ]


def rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
