"""Exact production provenance for delta-minimize compiler and inspector evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ...layout.objects import unit_paths
from .contracts import DeltaMinimizeError

_COMPILER_CONTEXT_SCHEMA = "delta-minimize-compiler-context.v1"
_COMPILER_IDENTITY_SCHEMA = "delta-minimize-compiler-identity.v1"
_INSPECTOR_CONTEXT_SCHEMA = "delta-minimize-inspector-context.v1"
_MWCC_NAME = "mwcceppc.exe"
_DEFAULT_REMOTE_DIR = "/c/Users/mikes/code/melee"
_DEFAULT_REMOTE_CLI = (
    "/c/Users/mikes/code/melee-decomp/mwcc-inspector-package/mwcc-inspector/"
    "MwccInspectorCLI/bin/GC 1.0 Debug/net8.0/MwccInspectorCLI.exe"
)
_DEFAULT_REMOTE_BASH = "C:\\devkitPro\\msys2\\usr\\bin\\bash.exe"


def _canonical_hash(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _safe_file_hash(path: Path, *, reason: str) -> str:
    try:
        absolute = path.absolute()
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current /= part
            if current.is_symlink():
                raise OSError("symlinked context")
        if not absolute.is_file():
            raise OSError("missing context")
        return hashlib.sha256(absolute.read_bytes()).hexdigest()
    except OSError as error:
        raise DeltaMinimizeError(reason, {"path": str(path)}) from error


def _ninja_tool(root: Path, tool: str, target: str) -> str:
    try:
        result = subprocess.run(
            ["ninja", "-t", tool, target],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"ninja_tool": tool, "target": target},
        ) from error
    if result.returncode != 0:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {
                "ninja_tool": tool,
                "target": target,
                "stderr": result.stderr.strip(),
            },
        )
    return result.stdout


def _require_ninja_fresh(root: Path, target: str) -> None:
    """Fail closed unless Ninja's dry run proves the target needs no work."""

    try:
        result = subprocess.run(
            ["ninja", "-n", target],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"freshness_target": target},
        ) from error
    if (
        result.returncode != 0
        or result.stdout.strip() != "ninja: no work to do."
        or result.stderr.strip()
    ):
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {
                "freshness_target": target,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            },
        )


def _repo_token(token: str, root: Path) -> str:
    path = Path(token)
    if not path.is_absolute():
        return token
    try:
        relative = path.relative_to(root.absolute())
    except ValueError:
        return token
    return f"$REPO/{relative.as_posix()}"


def _normalized_compile_command(root: Path, source: Path, target: str) -> tuple[str, ...]:
    stdout = _ninja_tool(root, "commands", target)
    source_relative = source.absolute().relative_to(root.absolute()).as_posix()
    matches: list[tuple[str, ...]] = []
    for line in stdout.splitlines():
        try:
            tokens = tuple(shlex.split(line))
        except ValueError as error:
            raise DeltaMinimizeError("invalid-compiler-context") from error
        normalized = tuple(_repo_token(token, root) for token in tokens)
        if (
            "-c" in normalized
            and any(Path(token).name.lower() == _MWCC_NAME for token in normalized)
            and (source_relative in normalized or f"$REPO/{source_relative}" in normalized)
        ):
            matches.append(normalized)
    if len(matches) != 1:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"target": target, "compile_commands": len(matches)},
        )
    return matches[0]


def _dependency_rows(root: Path, source: Path, target: str) -> tuple[Mapping[str, str], ...]:
    lines = _ninja_tool(root, "deps", target).splitlines()
    if not lines:
        raise DeltaMinimizeError("invalid-compiler-context", {"target": target})
    header = re.fullmatch(r".+: #deps ([0-9]+), .+ \(VALID\)", lines[0])
    if header is None:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"target": target, "dependency_state": lines[0]},
        )
    raw_dependencies = [line.strip() for line in lines[1:] if line.strip()]
    if len(raw_dependencies) != int(header.group(1)):
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"target": target, "dependency_count": len(raw_dependencies)},
        )
    root_resolved = root.resolve(strict=True)
    rows: dict[str, str] = {}
    source_relative = source.resolve(strict=True).relative_to(root_resolved).as_posix()
    for raw in raw_dependencies:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        digest = _safe_file_hash(candidate, reason="invalid-compiler-context")
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(root_resolved).as_posix()
        except (OSError, ValueError) as error:
            raise DeltaMinimizeError(
                "invalid-compiler-context",
                {"target": target, "dependency": raw},
            ) from error
        rows[relative] = digest
    if source_relative not in rows:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"target": target, "missing_dependency": source_relative},
        )
    return tuple({"path": path, "sha256": rows[path]} for path in sorted(rows))


def _compiler_context_snapshot(
    root: Path,
    source: Path,
    target: str,
) -> tuple[tuple[str, ...], tuple[Mapping[str, str], ...]]:
    return (
        _normalized_compile_command(root, source, target),
        _dependency_rows(root, source, target),
    )


def compiler_provenance(root: Path, source: Path) -> tuple[str, str]:
    """Hash the resolved compile command, dependency closure, and compiler bytes."""

    try:
        paths = unit_paths(root, source)
        target = paths.our_obj.absolute().relative_to(root.absolute()).as_posix()
        _require_ninja_fresh(root, target)
        first_snapshot = _compiler_context_snapshot(root, source, target)
        _require_ninja_fresh(root, target)
        second_snapshot = _compiler_context_snapshot(root, source, target)
        _require_ninja_fresh(root, target)
    except (OSError, ValueError) as error:
        raise DeltaMinimizeError("invalid-compiler-context") from error
    if first_snapshot != second_snapshot:
        raise DeltaMinimizeError(
            "invalid-compiler-context",
            {"target": target, "reason": "unstable-compiler-context"},
        )
    command, dependencies = second_snapshot
    cflags_hash = _canonical_hash(
        {
            "schema_version": _COMPILER_CONTEXT_SCHEMA,
            "target": target,
            "command": command,
            "dependencies": dependencies,
        }
    )
    compiler_tokens = [token for token in command if Path(token).name.lower() == _MWCC_NAME]
    if len(compiler_tokens) != 1:
        raise DeltaMinimizeError("invalid-compiler-context", {"target": target})
    compiler_token = compiler_tokens[0]
    if compiler_token.startswith("$REPO/"):
        compiler_path = root / compiler_token.removeprefix("$REPO/")
    elif Path(compiler_token).is_absolute():
        compiler_path = Path(compiler_token)
    else:
        compiler_path = root / compiler_token
    compiler_hash = _safe_file_hash(compiler_path, reason="invalid-compiler-context")
    config_rows = []
    for relative in ("config/GALE01/config.yml", "configure.py"):
        path = root / relative
        if path.exists():
            config_rows.append(
                {
                    "path": relative,
                    "sha256": _safe_file_hash(path, reason="invalid-compiler-context"),
                }
            )
    compiler_fingerprint = (
        "mwcc-context:"
        + _canonical_hash(
            {
                "schema_version": _COMPILER_IDENTITY_SCHEMA,
                "compiler": compiler_token,
                "compiler_sha256": compiler_hash,
                "configuration": config_rows,
            }
        )
    )
    return cflags_hash, compiler_fingerprint


def _resolve_local_commit(root: Path, ref: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DeltaMinimizeError("invalid-inspector-context") from error
    commit = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise DeltaMinimizeError(
            "invalid-inspector-context",
            {"remote_ref": ref, "stderr": result.stderr.strip()},
        )
    return commit


def _effective_remote_ref(root: Path, env: Mapping[str, str]) -> tuple[str, str, str]:
    override = env.get("MWCC_INSPECT_REMOTE_REF", "")
    if override:
        return override, _resolve_local_commit(root, override), "MWCC_INSPECT_REMOTE_REF"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DeltaMinimizeError("invalid-inspector-context") from error
    upstream = result.stdout.strip() if result.returncode == 0 else ""
    if upstream:
        return upstream, _resolve_local_commit(root, upstream), "local-upstream"
    selected = env.get("MWCC_INSPECT_DEFAULT_REMOTE_REF") or "master"
    return selected, _resolve_local_commit(root, selected), "default-remote-ref"


def inspector_provenance(
    root: Path,
    diff_capture: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Hash the actual workflow scripts and effective remote inspector identity."""

    values = os.environ if env is None else env
    workflow = root / "tools/workflow/mwcc-inspect.sh"
    remote_dir = values.get("MWCC_INSPECT_REMOTE_DIR") or _DEFAULT_REMOTE_DIR
    remote_ref_input, remote_ref, remote_ref_source = _effective_remote_ref(root, values)
    payload = {
        "schema_version": _INSPECTOR_CONTEXT_SCHEMA,
        "workflow_sha256": _safe_file_hash(workflow, reason="invalid-inspector-context"),
        "diff_capture_sha256": _safe_file_hash(diff_capture, reason="invalid-inspector-context"),
        "host": values.get("MWCC_INSPECT_HOST") or "nzxt-local",
        "connect_timeout": values.get("MWCC_INSPECT_CONNECT_TIMEOUT") or "10",
        "remote_dir": remote_dir,
        "remote_cli": values.get("MWCC_INSPECT_CLI") or _DEFAULT_REMOTE_CLI,
        "remote_bash": values.get("MWCC_INSPECT_REMOTE_BASH") or _DEFAULT_REMOTE_BASH,
        "remote_compiler": f"{remote_dir}/build/compilers/GC/1.2.5n/mwcceppc.exe",
        "remote_ref_input": remote_ref_input,
        "remote_ref": remote_ref,
        "remote_ref_source": remote_ref_source,
    }
    return f"mwcc-inspect-context:{_canonical_hash(payload)}"
