"""Tests for conservative registered-worktree discovery and policy."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

worktrees = importlib.import_module("worktree_doctor.worktrees")


def record(
    path: bytes,
    head: bytes = b"a" * 40,
    branch: bytes = b"codex/test",
) -> bytes:
    return (
        b"worktree "
        + path
        + b"\0HEAD "
        + head
        + b"\0branch refs/heads/"
        + branch
        + b"\0\0"
    )


def detached_record(
    path: bytes,
    *,
    locked: bytes | None = None,
    prunable: bytes | None = None,
) -> bytes:
    fields = [b"worktree " + path, b"HEAD " + b"b" * 40, b"detached"]
    if locked is not None:
        fields.append(b"locked" + (b" " + locked if locked else b""))
    if prunable is not None:
        fields.append(b"prunable" + (b" " + prunable if prunable else b""))
    return b"\0".join(fields) + b"\0\0"


def test_parse_worktree_porcelain_preserves_branch_record(tmp_path: Path) -> None:
    path = os.fsencode(tmp_path / "agent checkout")

    parsed = worktrees.parse_worktree_porcelain(record(path), object_hex_length=40)

    assert parsed == (
        worktrees.RegisteredWorktree(
            path=Path(os.fsdecode(path)),
            head="a" * 40,
            branch="codex/test",
            detached=False,
            locked_reason=None,
            prunable_reason=None,
        ),
    )


def test_parse_worktree_porcelain_preserves_detached_flags(tmp_path: Path) -> None:
    path = os.fsencode(tmp_path / "detached")

    parsed = worktrees.parse_worktree_porcelain(
        detached_record(
            path,
            locked=b"administrative hold",
            prunable=b"gitdir file points to non-existent location",
        ),
        object_hex_length=40,
    )

    assert parsed[0].branch is None
    assert parsed[0].detached is True
    assert parsed[0].locked_reason == "administrative hold"
    assert parsed[0].prunable_reason == "gitdir file points to non-existent location"


def test_parse_worktree_porcelain_preserves_bare_flags(tmp_path: Path) -> None:
    parsed = worktrees.parse_worktree_porcelain(
        detached_record(os.fsencode(tmp_path / "detached"), locked=b"", prunable=b""),
        object_hex_length=40,
    )

    assert parsed[0].locked_reason == ""
    assert parsed[0].prunable_reason == ""


@pytest.mark.parametrize(
    "name",
    [
        "line\nbreak",
        "snowman-☃",
    ],
)
def test_parse_worktree_porcelain_preserves_filesystem_path(
    tmp_path: Path, name: str
) -> None:
    path = os.fsencode(tmp_path / name)

    parsed = worktrees.parse_worktree_porcelain(record(path), object_hex_length=40)

    assert parsed[0].path == Path(os.fsdecode(path))
    assert os.fsencode(parsed[0].path) == path


def test_parse_worktree_porcelain_round_trips_undecodable_path_bytes(
    tmp_path: Path,
) -> None:
    path = os.fsencode(tmp_path) + b"/invalid-\xff"

    parsed = worktrees.parse_worktree_porcelain(record(path), object_hex_length=40)

    assert os.fsencode(parsed[0].path) == path


def test_parse_worktree_porcelain_supports_repository_oid_length(
    tmp_path: Path,
) -> None:
    payload = record(os.fsencode(tmp_path / "sha256"), head=b"f" * 64)

    parsed = worktrees.parse_worktree_porcelain(payload, object_hex_length=64)

    assert parsed[0].head == "f" * 64


def test_parse_worktree_porcelain_rejects_sha1_oid_for_sha256_repository() -> None:
    with pytest.raises(worktrees.WorktreeParseError, match="64-digit"):
        worktrees.parse_worktree_porcelain(
            record(b"/tmp/sha256", head=b"a" * 40), object_hex_length=64
        )


@pytest.mark.parametrize(
    "branch",
    [
        b"codex/foo..bar",
        b"codex/.hidden",
        b"codex/topic.lock",
        b"codex/topic@{1",
        b"codex//topic",
        b"codex/topic.",
    ],
)
def test_parse_worktree_porcelain_rejects_invalid_branch_ref(branch: bytes) -> None:
    with pytest.raises(worktrees.WorktreeParseError, match="valid Git ref"):
        worktrees.parse_worktree_porcelain(
            record(b"/tmp/invalid-branch", branch=branch), object_hex_length=40
        )


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        (
            "unknown field",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0future x\0branch refs/heads/codex/x\0\0",
        ),
        (
            "duplicate field",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0HEAD "
            + b"b" * 40
            + b"\0branch refs/heads/codex/x\0\0",
        ),
        (
            "missing HEAD",
            b"worktree /tmp/x\0branch refs/heads/codex/x\0\0",
        ),
        (
            "invalid OID characters",
            b"worktree /tmp/x\0HEAD "
            + b"g" * 40
            + b"\0branch refs/heads/codex/x\0\0",
        ),
        (
            "wrong OID length",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 64
            + b"\0branch refs/heads/codex/x\0\0",
        ),
        (
            "branch plus detached",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0branch refs/heads/codex/x\0detached\0\0",
        ),
        (
            "neither branch nor detached",
            b"worktree /tmp/x\0HEAD " + b"a" * 40 + b"\0\0",
        ),
        (
            "relative path",
            b"worktree relative\0HEAD "
            + b"a" * 40
            + b"\0branch refs/heads/codex/x\0\0",
        ),
        (
            "empty path",
            b"worktree \0HEAD "
            + b"a" * 40
            + b"\0branch refs/heads/codex/x\0\0",
        ),
        (
            "field before worktree",
            b"HEAD "
            + b"a" * 40
            + b"\0worktree /tmp/x\0branch refs/heads/codex/x\0\0",
        ),
        (
            "malformed branch prefix",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0branch codex/x\0\0",
        ),
        (
            "malformed detached value",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0detached yes\0\0",
        ),
        (
            "missing double-NUL record terminator",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0branch refs/heads/codex/x\0",
        ),
        (
            "trailing data",
            b"worktree /tmp/x\0HEAD "
            + b"a" * 40
            + b"\0branch refs/heads/codex/x\0\0trailing",
        ),
        ("empty input", b""),
        ("unexpected empty record", b"\0"),
    ],
    ids=lambda item: item if isinstance(item, str) else None,
)
def test_parse_worktree_porcelain_rejects_malformed(
    name: str, payload: bytes
) -> None:
    with pytest.raises(worktrees.WorktreeParseError, match=".+"):
        worktrees.parse_worktree_porcelain(payload, object_hex_length=40)


def test_parse_worktree_porcelain_rejects_duplicate_canonical_path() -> None:
    payload = record(b"/tmp/worktrees/agent") + record(
        b"/tmp/worktrees/../worktrees/agent", branch=b"claude/test"
    )

    with pytest.raises(worktrees.WorktreeParseError, match="duplicate canonical path"):
        worktrees.parse_worktree_porcelain(payload, object_hex_length=40)


@pytest.mark.parametrize("object_hex_length", [0, 39, 41, 65])
def test_parse_worktree_porcelain_rejects_unknown_object_length(
    object_hex_length: int,
) -> None:
    with pytest.raises(worktrees.WorktreeParseError, match="object length"):
        worktrees.parse_worktree_porcelain(
            record(b"/tmp/x"), object_hex_length=object_hex_length
        )


@pytest.mark.parametrize(("object_format", "expected"), [(b"sha1\n", 40), (b"sha256\n", 64)])
def test_repository_object_hex_length_queries_exact_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    object_format: bytes,
    expected: int,
) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args + (kwargs,))
        return subprocess.CompletedProcess(args[0], 0, object_format, b"")

    monkeypatch.setattr(worktrees.subprocess, "run", fake_run)

    assert worktrees.repository_object_hex_length(tmp_path) == expected
    assert calls == [
        (
            ["git", "-C", os.fspath(tmp_path), "rev-parse", "--show-object-format"],
            {"capture_output": True},
        )
    ]


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [(0, b"sha512\n"), (0, b"sha1 sha256\n"), (1, b"")],
)
def test_repository_object_hex_length_rejects_unknown_or_failed_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: bytes,
) -> None:
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, stdout, b"bad"),
    )

    with pytest.raises(worktrees.WorktreeParseError, match="object format"):
        worktrees.repository_object_hex_length(tmp_path)


def test_discover_registered_worktrees_runs_exact_git_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = record(os.fsencode(tmp_path / "linked"))
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        stdout = b"sha1\n" if args[-1] == "--show-object-format" else payload
        return subprocess.CompletedProcess(args, 0, stdout, b"")

    monkeypatch.setattr(worktrees.subprocess, "run", fake_run)

    assert worktrees.discover_registered_worktrees(tmp_path)[0].branch == "codex/test"
    assert calls == [
        (
            ["git", "-C", os.fspath(tmp_path), "rev-parse", "--show-object-format"],
            {"capture_output": True},
        ),
        (
            ["git", "-C", os.fspath(tmp_path), "worktree", "list", "--porcelain", "-z"],
            {"capture_output": True},
        ),
    ]


def test_discover_registered_worktrees_rejects_git_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if args[-1] == "--show-object-format":
            return subprocess.CompletedProcess(args, 0, b"sha1\n", b"")
        return subprocess.CompletedProcess(args, 1, b"", b"fatal")

    monkeypatch.setattr(worktrees.subprocess, "run", fake_run)

    with pytest.raises(worktrees.WorktreeParseError, match="worktree list"):
        worktrees.discover_registered_worktrees(tmp_path)


def registered(
    path: Path,
    *,
    branch: str | None = "codex/task",
    locked_reason: str | None = None,
    prunable_reason: str | None = None,
) -> worktrees.RegisteredWorktree:
    return worktrees.RegisteredWorktree(
        path=path,
        head="a" * 40,
        branch=branch,
        detached=branch is None,
        locked_reason=locked_reason,
        prunable_reason=prunable_reason,
    )


@pytest.mark.parametrize("branch", ["codex/task", "claude/task", "wall/task"])
def test_policy_allows_recognized_agent_branch(
    tmp_path: Path, branch: str
) -> None:
    root = tmp_path / "agents"
    main = root / "main"
    item = registered(root / "job", branch=branch)

    assert worktrees.policy_skip_reasons(
        item,
        main_worktree=main,
        current_worktree=main,
        agent_roots=(root,),
    ) == ()


@pytest.mark.parametrize(
    ("case", "path_factory", "branch", "locked", "prunable", "reason"),
    [
        ("main", lambda main, root: main, "codex/task", None, None, "main-worktree"),
        ("current", lambda main, root: root / "current", "codex/task", None, None, "current-worktree"),
        ("outside", lambda main, root: root.parent / "outside", "codex/task", None, None, "outside-agent-roots"),
        ("detached", lambda main, root: root / "detached", None, None, None, "detached-head"),
        ("locked", lambda main, root: root / "locked", "codex/task", "hold", None, "locked-worktree"),
        ("prunable", lambda main, root: root / "prunable", "codex/task", None, "stale", "prunable-worktree"),
        ("pr branch", lambda main, root: root / "pr", "pr/topic", None, None, "protected-pr-branch"),
        ("wip branch", lambda main, root: root / "wip", "wip/topic", None, None, "protected-wip-branch"),
        ("melee-pr path", lambda main, root: root / "melee-pr", "feature/topic", None, None, "protected-pr-path"),
        ("pr path", lambda main, root: root / "pr-topic", "feature/topic", None, None, "protected-pr-path"),
        ("unknown branch", lambda main, root: root / "other", "feature/topic", None, None, "unrecognized-agent-branch"),
    ],
)
def test_policy_classifies_ineligible_worktrees(
    tmp_path: Path,
    case: str,
    path_factory,
    branch: str | None,
    locked: str | None,
    prunable: str | None,
    reason: str,
) -> None:
    root = tmp_path / "agents"
    main = root / "main"
    current = root / "current" if case == "current" else main.parent / "command"
    item = registered(
        path_factory(main, root),
        branch=branch,
        locked_reason=locked,
        prunable_reason=prunable,
    )

    reasons = worktrees.policy_skip_reasons(
        item,
        main_worktree=main,
        current_worktree=current,
        agent_roots=(root,),
    )

    assert reasons == (reason,)


@pytest.mark.parametrize(
    ("path_name", "branch", "expected"),
    [
        ("ordinary", "pr/topic", ("protected-pr-branch",)),
        ("ordinary", "wip/topic", ("protected-wip-branch",)),
        ("melee-pr", "feature/topic", ("protected-pr-path",)),
        ("pr-review", "feature/topic", ("protected-pr-path",)),
    ],
)
def test_policy_protection_wins_before_generic_branch_rejection(
    tmp_path: Path, path_name: str, branch: str, expected: tuple[str, ...]
) -> None:
    root = tmp_path / "agents"
    main = root / "main"

    assert worktrees.policy_skip_reasons(
        registered(root / path_name, branch=branch),
        main_worktree=main,
        current_worktree=main,
        agent_roots=(root,),
    ) == expected


def test_policy_protected_path_is_reported_for_detached_worktree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"

    assert worktrees.policy_skip_reasons(
        registered(root / "pr-review", branch=None),
        main_worktree=root / "main",
        current_worktree=root / "current",
        agent_roots=(root,),
    ) == ("detached-head", "protected-pr-path")


def test_policy_uses_canonical_paths_for_roots_and_primary_checks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"
    main = root / "main"

    reasons = worktrees.policy_skip_reasons(
        registered(root / "nested" / ".." / "job"),
        main_worktree=main,
        current_worktree=root / "job",
        agent_roots=(root / ".",),
    )

    assert reasons == ("current-worktree",)
