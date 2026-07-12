"""Tests for conservative registered-worktree discovery and policy."""

from __future__ import annotations

import fcntl
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

worktrees = importlib.import_module("worktree_doctor.worktrees")
retained_evidence = importlib.import_module("worktree_doctor.retained_evidence")

MELEE_AGENT_ROOT = TOOLS_ROOT / "melee-agent"
if str(MELEE_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(MELEE_AGENT_ROOT))

mwcc_artifacts = importlib.import_module("src.mwcc_debug.artifacts")


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


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        check=True,
        capture_output=True,
    )


def _inspection_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Worktree Tests")
    (repo / ".gitignore").write_text(
        "build/\n.cache/\norig/\n__pycache__/\n.ninja_log\n.env\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "tracked.txt")
    _git(repo, "commit", "-qm", "fixture")
    linked = repo / ".claude" / "worktrees" / "job"
    linked.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", "-qb", "codex/job", os.fspath(linked))
    return repo, linked


def _quiet_snapshot() -> worktrees.ProcessSnapshot:
    return worktrees.ProcessSnapshot(paths=(), commands=(), errors=())


def test_inspection_uses_checkout_activity_not_old_head(tmp_path: Path) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    old = time.time() - 7 * 24 * 3600
    environment = os.environ.copy()
    environment["GIT_COMMITTER_DATE"] = f"@{int(old)}"
    subprocess.run(
        [
            "git",
            "-C",
            os.fspath(linked),
            "commit",
            "--amend",
            "--no-edit",
            f"--date=@{int(old)}",
        ],
        check=True,
        capture_output=True,
        env=environment,
    )
    head_time = int(_git(linked, "show", "-s", "--format=%ct").stdout)
    assert head_time == int(old)

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=24,
        now=time.time(),
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert item.last_activity > old + 24 * 3600
    assert "below-min-idle" in item.skip_reasons


@pytest.mark.parametrize("change", ["staged", "unstaged", "untracked"])
def test_inspection_reports_git_dirtiness(tmp_path: Path, change: str) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    if change == "staged":
        (linked / "added.txt").write_text("new\n", encoding="utf-8")
        _git(linked, "add", "added.txt")
    elif change == "unstaged":
        (linked / "tracked.txt").write_text("changed\n", encoding="utf-8")
    else:
        (linked / "untracked.txt").write_text("new\n", encoding="utf-8")

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert item.dirty is True
    assert "dirty-worktree" in item.skip_reasons


def test_inspection_reports_dirty_submodule(tmp_path: Path) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    submodule_source = tmp_path / "submodule-source"
    submodule_source.mkdir()
    _git(submodule_source, "init", "-q")
    _git(submodule_source, "config", "user.email", "tests@example.invalid")
    _git(submodule_source, "config", "user.name", "Worktree Tests")
    (submodule_source / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(submodule_source, "add", "tracked.txt")
    _git(submodule_source, "commit", "-qm", "fixture")
    _git(
        linked,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        os.fspath(submodule_source),
        "vendor/submodule",
    )
    _git(linked, "commit", "-qam", "add submodule")
    (linked / "vendor/submodule/tracked.txt").write_text("dirty\n", encoding="utf-8")

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert item.dirty is True
    assert "dirty-worktree" in item.skip_reasons


def test_ignored_rebuildable_file_does_not_make_git_dirty(tmp_path: Path) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    output = linked / "build" / "obj" / "file.o"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"object")

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert item.dirty is False
    assert "contains-unapproved-ignored" not in item.skip_reasons


def _age_worktree_activity(linked: Path, timestamp: float) -> Path:
    for root, directories, files in os.walk(linked, topdown=False):
        for name in (*files, *directories):
            os.utime(Path(root) / name, (timestamp, timestamp), follow_symlinks=False)
    os.utime(linked, (timestamp, timestamp))
    gitdir_text = (linked / ".git").read_text(encoding="utf-8").strip()
    assert gitdir_text.startswith("gitdir: ")
    admin = Path(gitdir_text.removeprefix("gitdir: "))
    if not admin.is_absolute():
        admin = linked / admin
    for relative in (Path("HEAD"), Path("logs/HEAD"), Path("index")):
        os.utime(admin / relative, (timestamp, timestamp))
    return admin


@pytest.mark.parametrize("activity", ["source", "build", "admin"])
def test_independent_fresh_activity_resets_idle_age(
    tmp_path: Path, activity: str
) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    build_output = linked / "build/obj/file.o"
    build_output.parent.mkdir(parents=True)
    build_output.write_bytes(b"object")
    now = time.time()
    old = now - 7 * 24 * 3600
    fresh = now - 60
    admin = _age_worktree_activity(linked, old)
    target = {
        "source": linked / "tracked.txt",
        "build": build_output,
        "admin": admin / "index",
    }[activity]
    os.utime(target, (fresh, fresh))

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=24,
        now=now,
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert item.last_activity is not None
    assert item.last_activity == pytest.approx(fresh)
    assert "below-min-idle" in item.skip_reasons


@pytest.mark.parametrize("relative", [Path(".env"), Path("build/crash.dump")])
def test_inspection_blocks_unapproved_ignored_content(
    tmp_path: Path, relative: Path
) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    path = linked / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"sensitive")

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert "contains-unapproved-ignored" in item.skip_reasons


def test_tree_walk_sums_allocated_blocks_without_following_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    local = root / "local"
    local.write_bytes(b"local")
    external = tmp_path / "external"
    external.write_bytes(b"x" * 1024 * 1024)
    link = root / "link"
    link.symlink_to(external)

    estimated, _activity, errors = worktrees._walk_tree(root)

    assert errors == ()
    assert estimated == sum(
        path.lstat().st_blocks * 512 for path in (root, local, link)
    )


def test_tree_walk_fails_closed_on_scan_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(
        worktrees.os, "scandir", lambda _fd: (_ for _ in ()).throw(OSError("denied"))
    )

    assert worktrees._walk_tree(root) == (0, 0.0, ("scan-failed",))


def test_tree_walk_closes_duplicated_scan_descriptors(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    before = len(os.listdir("/dev/fd"))

    for _ in range(25):
        assert worktrees._walk_tree(root)[2] == ()

    assert len(os.listdir("/dev/fd")) == before


def test_inspection_rejects_future_activity_timestamp(tmp_path: Path) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    future = time.time() + 3600
    os.utime(linked / "tracked.txt", (future, future))

    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        now=time.time(),
        process_snapshot=_quiet_snapshot(),
    )
    item = next(record for record in report.records if record.path == linked)

    assert "clock-skew" in item.skip_reasons


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"build/file.o", "ignored-inventory-invalid"),
        (b"\0", "ignored-inventory-invalid"),
        (b"/absolute\0", "ignored-inventory-invalid"),
        (b"build/../secret\0", "ignored-inventory-invalid"),
        (b"build/./file.o\0", "ignored-inventory-invalid"),
        (b"build/x\0build/x\0", "ignored-inventory-invalid"),
    ],
)
def test_ignored_inventory_rejects_malformed_nul_payload(
    tmp_path: Path, payload: bytes, reason: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    entries, errors = worktrees._parse_ignored_inventory(root, payload)

    assert entries == ()
    assert errors == (reason,)


def test_ignored_inventory_preserves_newline_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    relative = Path("build/line\nbreak")
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"data")

    entries, errors = worktrees._parse_ignored_inventory(
        root, os.fsencode(relative) + b"\0"
    )

    assert errors == ()
    assert entries[0].relative == relative


def test_ignored_inventory_rejects_raw_dot_component_before_path_normalization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    path = root / "build" / "file.o"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"data")

    assert worktrees._parse_ignored_inventory(root, b"build/./file.o\0") == (
        (),
        ("ignored-inventory-invalid",),
    )


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "payload"),
    [
        ("_IGNORED_MAX_BYTES", 1, b"x\0"),
        ("_IGNORED_MAX_ENTRIES", 0, b"x\0"),
    ],
)
def test_ignored_inventory_enforces_bounds_before_opening_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    payload: bytes,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(worktrees, limit_name, limit_value)

    assert worktrees._parse_ignored_inventory(root, payload) == (
        (),
        ("ignored-inventory-invalid",),
    )


@pytest.mark.parametrize(
    ("relative", "approved"),
    [
        ("build/obj/file.o", True),
        (".cache/tool/file", True),
        ("package/__pycache__/x.pyc", True),
        (".pytest_cache/x", True),
        (".mypy_cache/x", True),
        ("htmlcov/index.html", True),
        ("build.ninja", True),
        (".ninja_deps", True),
        (".ninja_log", True),
        ("compile_commands.json", True),
        ("objdiff.json", True),
        ("ctx.c", True),
        ("ctx_includes.h", True),
        ("tools/melee-agent/.coverage", True),
        (".env", False),
        ("build/crash.dump", False),
        ("build/logs/output.txt", False),
        ("build/.venv/bin/python", False),
        ("build/.claude/session.json", False),
        ("build/candidates/output.bin", False),
    ],
)
def test_disposable_ignored_allowlist_and_denial_precedence(
    relative: str, approved: bool
) -> None:
    assert worktrees._is_disposable_ignored(Path(relative), "file") is approved


def test_generated_root_name_must_be_a_regular_file() -> None:
    assert worktrees._is_disposable_ignored(Path("build.ninja"), "directory") is False
    assert (
        worktrees._is_disposable_ignored(
            Path("tools/melee-agent/.coverage"), "symlink"
        )
        is False
    )


def test_retained_evidence_discovers_default_and_custom_manifest_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    default_run = mwcc_artifacts.create_run(root, command=("default",))
    default_run.finalize("completed")
    custom_run = mwcc_artifacts.create_run(
        root,
        command=("custom",),
        artifact_root=Path("build/custom-evidence"),
    )
    custom_run.finalize("completed")
    ignored = tuple(
        worktrees.IgnoredEntry.from_path(root, path.relative_to(root))
        for path in (default_run.manifest_path, custom_run.manifest_path)
    )

    snapshot, errors = retained_evidence.discover_retained_evidence(root, ignored)

    assert errors == ()
    assert snapshot.roots == tuple(sorted((default_run.root, custom_run.root)))
    assert {item[0] for item in snapshot.manifests} == {
        default_run.manifest_path.relative_to(root),
        custom_run.manifest_path.relative_to(root),
    }


@pytest.mark.parametrize(
    "artifact_root", [None, Path("build/custom-evidence")], ids=["default", "custom"]
)
def test_inspection_blocks_retained_run_until_artifact_pruner_applies(
    tmp_path: Path, artifact_root: Path | None
) -> None:
    repo, linked = _inspection_fixture(tmp_path)
    run = mwcc_artifacts.create_run(
        linked, command=("fixture",), artifact_root=artifact_root
    )
    run.finalize("completed")

    before = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    before_item = next(item for item in before.records if item.path == linked)
    assert "retained-evidence-present" in before_item.skip_reasons

    plan = mwcc_artifacts.prune_runs(
        linked,
        artifact_root=artifact_root,
        max_age_days=0,
        max_total_bytes=0,
        apply=True,
    )
    assert plan.removed_run_dirs == (run.run_dir,)

    after = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=0,
        process_snapshot=_quiet_snapshot(),
    )
    after_item = next(item for item in after.records if item.path == linked)
    assert "retained-evidence-present" not in after_item.skip_reasons
    assert after_item.eligible is True


def test_dol_validation_requires_identity_checked_candidate_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = importlib.import_module("worktree_doctor")
    worktree = tmp_path / "worktree"
    dol = worktree / "orig/GALE01/sys/main.dol"
    dol.parent.mkdir(parents=True)
    candidate = tmp_path / "approved.dol"
    candidate.write_bytes(b"dol")
    monkeypatch.setattr(package, "DOL_CANDIDATES", [candidate])
    dol.symlink_to(os.path.relpath(candidate, start=dol.parent))

    identity, valid = worktrees._inspect_dol(worktree)

    assert valid is True
    assert identity is not None
    dol.unlink()
    dol.write_bytes(b"dol")
    assert worktrees._inspect_dol(worktree) == (None, False)


def test_dol_validation_rejects_symlinked_parent_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = importlib.import_module("worktree_doctor")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    external_orig = tmp_path / "external-orig"
    dol = external_orig / "GALE01/sys/main.dol"
    dol.parent.mkdir(parents=True)
    candidate = tmp_path / "approved.dol"
    candidate.write_bytes(b"dol")
    monkeypatch.setattr(package, "DOL_CANDIDATES", [candidate])
    dol.symlink_to(os.path.relpath(candidate, start=dol.parent))
    (worktree / "orig").symlink_to(external_orig, target_is_directory=True)

    assert worktrees._inspect_dol(worktree) == (None, False)


def test_dol_validation_does_not_lexically_collapse_target_symlink_before_dotdot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = importlib.import_module("worktree_doctor")
    worktree = tmp_path / "worktree"
    dol = worktree / "orig/GALE01/sys/main.dol"
    dol.parent.mkdir(parents=True)
    candidate = tmp_path / "approved.dol"
    candidate.write_bytes(b"approved")
    redirected = tmp_path / "external/nested"
    redirected.mkdir(parents=True)
    (tmp_path / "redirect").symlink_to(redirected, target_is_directory=True)
    monkeypatch.setattr(package, "DOL_CANDIDATES", [candidate])
    dol.symlink_to("../../../../redirect/../approved.dol")

    assert worktrees._inspect_dol(worktree) == (None, False)


def test_dol_validation_rejects_candidate_path_replaced_during_descriptor_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = importlib.import_module("worktree_doctor")
    worktree = tmp_path / "worktree"
    dol = worktree / "orig/GALE01/sys/main.dol"
    dol.parent.mkdir(parents=True)
    candidate = tmp_path / "approved.dol"
    candidate.write_bytes(b"approved")
    displaced = tmp_path / "displaced.dol"
    monkeypatch.setattr(package, "DOL_CANDIDATES", [candidate])
    dol.symlink_to(os.path.relpath(candidate, start=dol.parent))
    real_open = worktrees.os.open
    replaced = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if os.fspath(path) == candidate.name and not replaced:
            replaced = True
            candidate.replace(displaced)
            candidate.write_bytes(b"replacement")
        return descriptor

    monkeypatch.setattr(worktrees.os, "open", racing_open)

    assert worktrees._inspect_dol(worktree) == (None, False)
    assert replaced is True


def test_malformed_manifest_like_ignored_file_remains_unapproved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    manifest = root / "build" / "custom" / "bad" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"artifact_format": "wrong"}), encoding="utf-8")
    entry = worktrees.IgnoredEntry.from_path(root, manifest.relative_to(root))

    snapshot, errors = retained_evidence.discover_retained_evidence(root, (entry,))

    assert snapshot.roots == ()
    assert errors == ()
    assert worktrees._classify_ignored((entry,), snapshot, None, None) == (
        (manifest.relative_to(root),),
        False,
    )


def test_process_snapshot_matches_absolute_lsof_paths_and_ps_argv(tmp_path: Path) -> None:
    worktree = tmp_path / "agent"
    snapshot = worktrees.ProcessSnapshot(
        paths=((11, worktree / "open.txt"),),
        commands=((12, f"python {worktree}/job.py"),),
        errors=(),
    )

    assert snapshot.active_pids(worktree, worktree) == (11, 12)


def test_process_parsers_ignore_nonabsolute_lsof_names_and_self_pid(tmp_path: Path) -> None:
    paths = worktrees._parse_lsof(
        b"p10\0fcwd\0n/tmp/work\0p11\0f3\0nTCP *:80\0",
        self_pid=11,
    )
    commands = worktrees._parse_ps(
        b"10 python /tmp/work/job.py\n11 doctor\n", self_pid=11
    )

    assert paths == ((10, Path("/tmp/work").resolve(strict=False)),)
    assert commands == ((10, "python /tmp/work/job.py"),)


def _scripted_popen(scripts: list[str]):
    def factory(_args, **kwargs):
        return subprocess.Popen([sys.executable, "-c", scripts.pop(0)], **kwargs)

    return factory


def test_collect_process_snapshot_uses_bounded_lsof_and_ps() -> None:
    snapshot = worktrees.collect_process_snapshot(
        popen_factory=_scripted_popen(
            [
                "import sys; sys.stdout.write('p77\\nfcwd\\nn/tmp/work\\n')",
                "import sys; sys.stdout.write('78 python /tmp/work/job.py\\n')",
            ]
        )
    )

    assert snapshot.errors == ()
    assert snapshot.paths == ((77, Path("/tmp/work").resolve(strict=False)),)
    assert snapshot.commands == ((78, "python /tmp/work/job.py"),)


def test_bounded_command_does_not_wait_forever_for_stubborn_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    class StubbornProcess:
        stdout = child.stdout
        stderr = child.stderr
        wait_timeouts: list[float | None] = []
        killed = False

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout=None):
            self.wait_timeouts.append(timeout)
            if timeout is None:
                raise AssertionError("unbounded wait")
            raise subprocess.TimeoutExpired(("stubborn",), timeout)

    process = StubbornProcess()
    monkeypatch.setattr(worktrees, "_PROCESS_TIMEOUT", 0.01)
    try:
        assert worktrees._bounded_command(
            ("stubborn",), popen_factory=lambda *_args, **_kwargs: process
        ) == (b"", b"", "process-query-failed")
        assert process.killed is True
        assert process.wait_timeouts
        assert all(timeout is not None for timeout in process.wait_timeouts)
    finally:
        child.kill()
        child.wait(timeout=1)


@pytest.mark.parametrize(
    ("scripts", "patches", "expected"),
    [
        (["raise SystemExit(2)"], {}, "process-query-failed"),
        (
            ["import sys; sys.stdout.write('x' * 17)"],
            {"_PROCESS_STDOUT_MAX": 16},
            "process-query-overflow",
        ),
        (
            ["import sys; sys.stderr.write('x' * 17)"],
            {"_PROCESS_STDERR_MAX": 16},
            "process-query-overflow",
        ),
        (
            ["import time; time.sleep(1)"],
            {"_PROCESS_TIMEOUT": 0.01},
            "process-query-failed",
        ),
        (
            ["import sys; sys.stdout.write('p1\\nf1\\nn/tmp\\n')", ""],
            {"_PROCESS_RECORD_MAX": 2},
            "process-query-overflow",
        ),
        (
            ["import sys; sys.stdout.write('n/tmp/no-pid\\n')", ""],
            {},
            "process-query-failed",
        ),
    ],
    ids=["nonzero", "stdout", "stderr", "timeout", "records", "malformed"],
)
def test_collect_process_snapshot_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    scripts: list[str],
    patches: dict[str, float | int],
    expected: str,
) -> None:
    for name, value in patches.items():
        monkeypatch.setattr(worktrees, name, value)

    snapshot = worktrees.collect_process_snapshot(
        popen_factory=_scripted_popen(list(scripts))
    )

    assert snapshot.paths == ()
    assert snapshot.commands == ()
    assert snapshot.errors == (expected,)


def _retirement_record(
    path: Path,
    *,
    branch: str = "codex/retire",
    head: str = "a" * 40,
    estimated_disk_bytes: int = 4096,
    last_activity: float = 1.0,
) -> worktrees.WorktreeRecord:
    path.mkdir(parents=True, exist_ok=True)
    identity = path.lstat()
    return worktrees.WorktreeRecord(
        path=path,
        canonical_path=path.resolve(strict=False),
        path_device=identity.st_dev,
        path_inode=identity.st_ino,
        head=head,
        branch=branch,
        detached=False,
        locked_reason=None,
        prunable_reason=None,
        branch_head=head,
        estimated_disk_bytes=estimated_disk_bytes,
        last_activity=last_activity,
        dirty=False,
        ignored_entries=(),
        unapproved_ignored_paths=(),
        retained_evidence=retained_evidence.RetainedEvidenceSnapshot((), ()),
        asset_snapshot=None,
        dol_identity=None,
        active_pids=(),
        merged_into_master=None,
        eligible=True,
        skip_reasons=(),
    )


def _retirement_report(
    tmp_path: Path,
    records: tuple[worktrees.WorktreeRecord, ...],
    *,
    global_errors: tuple[str, ...] = (),
) -> worktrees.WorktreeReport:
    common_git_dir = tmp_path / "common-git"
    common_git_dir.mkdir(exist_ok=True)
    return worktrees.WorktreeReport(
        repo_root=tmp_path / "repo",
        common_git_dir=common_git_dir,
        current_worktree=tmp_path / "repo",
        min_idle_hours=24,
        records=records,
        global_errors=global_errors,
    )


def test_retirement_dry_run_is_canonical_ordered_and_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    later = _retirement_record(tmp_path / "z-agent", branch="codex/z")
    earlier = _retirement_record(tmp_path / "a-agent", branch="codex/a")
    report = _retirement_report(tmp_path, (later, earlier))
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("dry-run executed a command"),
    )

    result = worktrees.retire_worktrees(report, apply=False)

    assert [item.path for item in result.planned] == [earlier.path, later.path]
    assert result.removed == ()
    assert result.skipped == ()
    assert result.errors == ()


def test_retirement_apply_lock_contention_fails_before_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _retirement_record(tmp_path / "agent")
    report = _retirement_report(tmp_path, (item,))
    lock_path = report.common_git_dir / "worktree-doctor-retirement.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("lock failure executed Git"),
    )
    try:
        result = worktrees.retire_worktrees(report, apply=True)
    finally:
        os.close(descriptor)

    assert result.planned == ()
    assert result.removed == ()
    assert result.skipped == ()
    assert [error.reason for error in result.errors] == ["retirement-lock-unavailable"]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("porcelain", "worktree-porcelain-invalid"),
        ("process", "process-query-failed"),
    ],
)
def test_retirement_global_preflight_failure_prevents_every_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: str,
) -> None:
    item = _retirement_record(tmp_path / "agent")
    report = _retirement_report(tmp_path, (item,))

    def fail_preflight(*_args, **_kwargs):
        if failure == "porcelain":
            raise worktrees.WorktreeParseError("malformed porcelain")
        return replace(report, global_errors=("process-query-failed",))

    monkeypatch.setattr(worktrees, "inspect_worktrees", fail_preflight)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    result = worktrees.retire_worktrees(report, apply=True)

    assert result.planned == ()
    assert result.removed == ()
    assert [error.reason for error in result.errors] == [expected]
    assert not any("remove" in args for args in calls)


def _local_revalidation_mutation(
    name: str, item: worktrees.WorktreeRecord
) -> tuple[worktrees.WorktreeRecord | None, str]:
    if name == "dirty":
        return replace(item, dirty=True, eligible=False, skip_reasons=("dirty-worktree",)), "dirty-worktree"
    if name == "active":
        return replace(item, active_pids=(123,), eligible=False, skip_reasons=("active-process",)), "active-process"
    if name == "locked":
        return replace(item, locked_reason="hold", eligible=False, skip_reasons=("locked-worktree",)), "locked-worktree"
    if name == "detached":
        return replace(
            item, branch=None, branch_head=None, detached=True, eligible=False, skip_reasons=("detached-head",)
        ), "detached-head"
    if name == "unregistered":
        return None, "changed-during-retirement"
    if name == "head":
        return replace(item, head="b" * 40, branch_head="b" * 40), "changed-during-retirement"
    if name == "branch":
        return replace(item, branch="codex/changed"), "changed-during-retirement"
    if name == "branch-ref":
        return replace(
            item, branch_head="b" * 40, eligible=False, skip_reasons=("branch-head-mismatch",)
        ), "branch-head-mismatch"
    if name == "inode":
        assert item.path_inode is not None
        return replace(item, path_inode=item.path_inode + 1), "replaced-during-retirement"
    if name == "newer":
        assert item.last_activity is not None
        return replace(item, last_activity=item.last_activity + 1), "changed-during-retirement"
    if name == "disk":
        return replace(item, estimated_disk_bytes=item.estimated_disk_bytes + 512), "changed-during-retirement"
    if name == "inventory":
        entry = worktrees.IgnoredEntry(Path("build/new.o"), "file", 1, 2, 3, 4.0)
        return replace(item, ignored_entries=(entry,)), "changed-during-retirement"
    if name == "retained":
        snapshot = retained_evidence.RetainedEvidenceSnapshot((Path("build/runs"),), ())
        return replace(
            item, retained_evidence=snapshot, eligible=False, skip_reasons=("retained-evidence-present",)
        ), "retained-evidence-present"
    if name == "unknown-ignored":
        return replace(
            item,
            unapproved_ignored_paths=(Path(".env"),),
            eligible=False,
            skip_reasons=("contains-unapproved-ignored",),
        ), "contains-unapproved-ignored"
    if name == "asset":
        return replace(item, eligible=False, skip_reasons=("asset-validation-failed",)), "asset-validation-failed"
    raise AssertionError(name)


@pytest.mark.parametrize(
    "mutation",
    [
        "dirty",
        "active",
        "locked",
        "detached",
        "unregistered",
        "head",
        "branch",
        "branch-ref",
        "inode",
        "newer",
        "disk",
        "inventory",
        "retained",
        "unknown-ignored",
        "asset",
    ],
)
def test_retirement_revalidation_skips_changed_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    item = _retirement_record(tmp_path / "agent")
    report = _retirement_report(tmp_path, (item,))
    changed, expected = _local_revalidation_mutation(mutation, item)
    reports = [report, replace(report, records=() if changed is None else (changed,))]
    monkeypatch.setattr(worktrees, "inspect_worktrees", lambda *_args, **_kwargs: reports.pop(0))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )

    result = worktrees.retire_worktrees(report, apply=True)

    assert result.removed == ()
    assert [(skip.phase, skip.reason) for skip in result.skipped] == [("revalidate", expected)]
    assert result.errors == ()
    assert not any("remove" in args for args in calls)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("porcelain", "worktree-porcelain-invalid"),
        ("process", "process-query-failed"),
    ],
)
def test_retirement_global_revalidation_failure_stops_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: str,
) -> None:
    item = _retirement_record(tmp_path / "agent")
    report = _retirement_report(tmp_path, (item,))
    calls = 0

    def inspect(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return report
        if failure == "porcelain":
            raise worktrees.WorktreeParseError("malformed porcelain")
        return replace(report, global_errors=("process-query-failed",))

    monkeypatch.setattr(worktrees, "inspect_worktrees", inspect)
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("global failure attempted removal"),
    )

    result = worktrees.retire_worktrees(report, apply=True)

    assert len(result.planned) == 1
    assert result.removed == ()
    assert result.skipped == ()
    assert [error.reason for error in result.errors] == [expected]


def test_retirement_refreshes_processes_after_candidate_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _retirement_record(tmp_path / "agent")
    report = _retirement_report(tmp_path, (item,))
    reports = [report, report]
    monkeypatch.setattr(
        worktrees, "inspect_worktrees", lambda *_args, **_kwargs: reports.pop(0)
    )
    monkeypatch.setattr(
        worktrees,
        "collect_process_snapshot",
        lambda: worktrees.ProcessSnapshot(
            paths=((123, item.path / "late-open-file"),), commands=(), errors=()
        ),
    )
    monkeypatch.setattr(
        worktrees.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("late active process was removed"),
    )

    result = worktrees.retire_worktrees(report, apply=True)

    assert [(skip.phase, skip.reason) for skip in result.skipped] == [
        ("revalidate", "active-process")
    ]


def _old_retirement_fixture(tmp_path: Path, name: str) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    if not repo.exists():
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "tests@example.invalid")
        _git(repo, "config", "user.name", "Worktree Tests")
        (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        _git(repo, "add", ".gitignore", "tracked.txt")
        _git(repo, "commit", "-qm", "fixture")
    branch = f"codex/{name}"
    linked = repo / ".claude" / "worktrees" / name
    linked.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-qb", branch, os.fspath(linked))
    output = linked / "build/obj/file.o"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"object")
    _age_worktree_activity(linked, time.time() - 7 * 24 * 3600)
    return repo, linked, branch, _git(repo, "rev-parse", branch).stdout.strip().decode()


def test_retirement_apply_removes_checkout_and_preserves_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, linked, branch, original_head = _old_retirement_fixture(tmp_path, "one")
    monkeypatch.setattr(worktrees, "collect_process_snapshot", _quiet_snapshot)
    commands: list[list[str]] = []
    real_run = subprocess.run

    def recording_run(args, **kwargs):
        commands.append([os.fspath(value) for value in args])
        return real_run(args, **kwargs)

    monkeypatch.setattr(worktrees.subprocess, "run", recording_run)
    monkeypatch.setattr(shutil, "rmtree", lambda *_args, **_kwargs: pytest.fail("recursive deletion used"))
    report = worktrees.inspect_worktrees(
        repo,
        current_worktree=repo,
        min_idle_hours=24,
        process_snapshot=_quiet_snapshot(),
    )

    result = worktrees.retire_worktrees(report, apply=True)

    assert [item.path for item in result.removed] == [linked]
    assert not linked.exists()
    assert (
        real_run(
            ["git", "-C", os.fspath(repo), "show-ref", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
        ).returncode
        == 0
    )
    assert (
        real_run(["git", "-C", os.fspath(repo), "rev-parse", branch], capture_output=True).stdout.strip().decode()
        == original_head
    )
    assert [command for command in commands if "remove" in command] == [
        [
            "git",
            "-C",
            os.fspath(repo.resolve(strict=False)),
            "worktree",
            "remove",
            "--",
            os.fspath(linked),
        ]
    ]
    flattened = [token for command in commands for token in command]
    assert "--force" not in flattened
    assert "-d" not in flattened
    assert "-D" not in flattened
    assert "update-ref" not in flattened
    assert "prune" not in flattened


def test_retirement_path_absence_check_detects_dangling_symlink(
    tmp_path: Path,
) -> None:
    dangling = tmp_path / "recreated-worktree"
    dangling.symlink_to(tmp_path / "missing-target")

    assert worktrees._path_exists_nofollow(dangling) is True


def test_retirement_late_global_failure_reports_partial_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, first, _branch, _head = _old_retirement_fixture(tmp_path, "a-first")
    _repo, second, _branch, _head = _old_retirement_fixture(tmp_path, "b-second")
    monkeypatch.setattr(worktrees, "collect_process_snapshot", _quiet_snapshot)
    real_inspect = worktrees.inspect_worktrees
    calls = 0

    def inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        current = real_inspect(*args, process_snapshot=_quiet_snapshot(), **kwargs)
        if calls == 3:
            return replace(current, global_errors=("process-query-failed",))
        return current

    monkeypatch.setattr(worktrees, "inspect_worktrees", inspect)
    initial = real_inspect(repo, current_worktree=repo, min_idle_hours=24, process_snapshot=_quiet_snapshot())

    result = worktrees.retire_worktrees(initial, apply=True)

    assert [item.path for item in result.removed] == [first]
    assert result.skipped == ()
    assert [error.reason for error in result.errors] == ["process-query-failed"]
    assert not first.exists()
    assert second.exists()


def test_retirement_local_failure_continues_to_next_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, first, _branch, _head = _old_retirement_fixture(tmp_path, "a-first")
    _repo, second, _branch, _head = _old_retirement_fixture(tmp_path, "b-second")
    monkeypatch.setattr(worktrees, "collect_process_snapshot", _quiet_snapshot)
    real_inspect = worktrees.inspect_worktrees
    calls = 0

    def inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (first / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        return real_inspect(*args, process_snapshot=_quiet_snapshot(), **kwargs)

    monkeypatch.setattr(worktrees, "inspect_worktrees", inspect)
    initial = real_inspect(repo, current_worktree=repo, min_idle_hours=24, process_snapshot=_quiet_snapshot())

    result = worktrees.retire_worktrees(initial, apply=True)

    assert [(item.path, item.reason) for item in result.skipped] == [(first, "dirty-worktree")]
    assert [item.path for item in result.removed] == [second]
    assert result.errors == ()
    assert first.exists()
    assert not second.exists()
