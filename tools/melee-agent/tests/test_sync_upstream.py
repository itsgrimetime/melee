"""Regression tests for tools/workflow/sync-upstream.sh."""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _upstream_configure(object_line: str) -> str:
    return textwrap.dedent(
        f"""\
        import sys
        from pathlib import Path

        from tools.project import ProjectConfig

        class Parser:
            def add_argument(self, *args, **kwargs):
                pass

            def parse_args(self):
                return type("Args", (), {{"mode": "configure"}})()

        parser = Parser()
        parser.add_argument(
            "--require-protos",
            dest="require_protos",
            action="store_true",
            help="require function prototypes",
        )

        args = parser.parse_args()
        config = ProjectConfig()
        config.wibo_tag = "0.7.0"

        config.libs = [
            {object_line},
        ]

        config.progress_report_args = [
            # Marks relocations as mismatching if the target value is different
            f"--config functionRelocDiffs={{args.reloc_diffs}}",
        ]

        if args.mode == "configure":
            if args.always_apply:
                config.custom_build_steps = {{"post-ok": []}}

            # Write build.ninja and objdiff.json
            generate_build(config)
        elif args.mode == "progress":
            calculate_progress(config)
        else:
            sys.exit("Unknown mode: " + args.mode)
        """
    )


def _fork_configure(object_line: str) -> str:
    return textwrap.dedent(
        f"""\
        import sys
        from pathlib import Path

        from tools.project import ProjectConfig

        class Parser:
            def add_argument(self, *args, **kwargs):
                pass

            def parse_args(self):
                return type("Args", (), {{"mode": "configure"}})()

        parser = Parser()
        parser.add_argument(
            "--require-protos",
            dest="require_protos",
            action="store_true",
            default=True,
            help="require function prototypes (default: enabled)",
        )
        parser.add_argument(
            "--no-require-protos",
            dest="require_protos",
            action="store_false",
            help="disable function prototype requirement",
        )

        args = parser.parse_args()
        config = ProjectConfig()
        config.wibo_tag = "1.0.0"

        config.libs = [
            {object_line},
        ]

        config.progress_report_args = [
            # Marks relocations as mismatching if the target value is different
            # Default is "functionRelocDiffs=none", which is most lenient
            # "--config functionRelocDiffs=data_value",
        ]

        def _purge_wrong_arch_wibo(config: ProjectConfig) -> None:
            wibo = config.build_dir / "tools" / "wibo"
            if not wibo.exists():
                return
            wibo.unlink()

        if args.mode == "configure":
            # Write build.ninja and objdiff.json
            _purge_wrong_arch_wibo(config)
            generate_build(config)
        elif args.mode == "progress":
            calculate_progress(config)
        else:
            sys.exit("Unknown mode: " + args.mode)
        """
    )


@pytest.mark.parametrize(
    "merged_decomp_above_tooling",
    [False, True],
    ids=["tooling-at-tip", "merged-decomp-above-tooling"],
)
def test_sync_upstream_preserves_upstream_configure_and_clears_config_json(
    tmp_path: Path,
    merged_decomp_above_tooling: bool,
) -> None:
    upstream_work = tmp_path / "upstream-work"
    upstream_work.mkdir()
    _git(upstream_work, "init", "-b", "master")
    _git(upstream_work, "config", "user.email", "agent@example.test")
    _git(upstream_work, "config", "user.name", "Agent")
    (upstream_work / "configure.py").write_text(
        _upstream_configure('Object(NonMatching, "melee/it/old.c")'),
        encoding="utf-8",
    )
    upstream_workflows = upstream_work / ".github" / "workflows"
    upstream_packages = upstream_work / ".github" / "packages"
    upstream_workflows.mkdir(parents=True)
    upstream_packages.mkdir()
    upstream_check = upstream_work / "tools" / "check"
    upstream_check.mkdir(parents=True)
    (upstream_check / "main.py").write_text("upstream check v1\n")
    (upstream_workflows / "build.yml").write_text("upstream build v1\n")
    (upstream_workflows / "publish-packages.yml").write_text(
        "obsolete publisher\n"
    )
    (upstream_packages / "obsolete.txt").write_text("obsolete package\n")
    (upstream_work / ".pre-commit-config.yaml").write_text(
        "repos:\n- repo: local\n  hooks:\n"
        "    - id: upstream-hook-v1\n"
        "    - id: style-check\n"
        "    - id: clang-format\n"
        "    - id: editorconfig-checker\n"
    )
    _git(
        upstream_work,
        "add",
        "configure.py",
        ".github",
        ".pre-commit-config.yaml",
        "tools/check/main.py",
    )
    _git(upstream_work, "commit", "-m", "upstream baseline")

    upstream_bare = tmp_path / "upstream.git"
    _git(tmp_path, "clone", "--bare", str(upstream_work), str(upstream_bare))

    repo = tmp_path / "melee"
    _git(tmp_path, "clone", str(upstream_bare), str(repo))
    _git(repo, "config", "user.email", "agent@example.test")
    _git(repo, "config", "user.name", "Agent")
    _git(repo, "remote", "rename", "origin", "upstream")

    workflow_dir = repo / "tools" / "workflow"
    workflow_dir.mkdir(parents=True)
    shutil.copy2(
        TOOLS_ROOT / "workflow" / "sync-upstream.sh",
        workflow_dir / "sync-upstream.sh",
    )
    (repo / "configure.py").write_text(
        _fork_configure('Object(NonMatching, "melee/it/old.c")'),
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "capabilities-drift.yml").write_text(
        "fork capability workflow\n"
    )
    (repo / ".pre-commit-config.yaml").write_text(
        "repos:\n- repo: local\n  hooks:\n  - id: stale-fork-hook\n"
    )
    _git(
        repo,
        "add",
        "tools/workflow/sync-upstream.sh",
        "configure.py",
        ".github",
        ".pre-commit-config.yaml",
    )
    _git(repo, "commit", "-m", "fork tooling")

    if merged_decomp_above_tooling:
        local_match = repo / "src" / "matched.c"
        local_match.parent.mkdir()
        local_match.write_text("void matched(void) {}\n", encoding="utf-8")
        _git(repo, "add", "src/matched.c")
        _git(repo, "commit", "-m", "match function")

    stale_config = repo / "build" / "GALE01" / "config.json"
    stale_config.parent.mkdir(parents=True)
    stale_config.write_text('{"version": "v1.8.3", "units": []}\n', encoding="utf-8")
    personal_notes = repo / "personal-notes.txt"
    personal_notes.write_text("keep me untracked\n", encoding="utf-8")
    assert "?? build/" in _git(repo, "status", "--porcelain").stdout

    (upstream_work / "configure.py").write_text(
        _upstream_configure('Object(NonMatching, "melee/it/new_split.c")'),
        encoding="utf-8",
    )
    (upstream_workflows / "build.yml").write_text("upstream build v2\n")
    (upstream_workflows / "publish-packages.yml").unlink()
    (upstream_packages / "obsolete.txt").unlink()
    (upstream_check / "main.py").write_text("upstream check v2\n")
    if merged_decomp_above_tooling:
        upstream_match = upstream_work / "src" / "matched.c"
        upstream_match.parent.mkdir()
        upstream_match.write_text("void matched(void) {}\n", encoding="utf-8")
    (upstream_work / ".pre-commit-config.yaml").write_text(
        "repos:\n- repo: local\n  hooks:\n"
        "    - id: upstream-hook-v2\n"
        "    - id: style-check\n"
        "    - id: clang-format\n"
        "    - id: editorconfig-checker\n"
    )
    _git(upstream_work, "add", "-A")
    _git(upstream_work, "commit", "-m", "upstream split")
    _git(upstream_work, "push", str(upstream_bare), "master")

    result = subprocess.run(
        ["bash", "tools/workflow/sync-upstream.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    committed_configure = _git(repo, "show", "HEAD:configure.py").stdout
    assert 'Object(NonMatching, "melee/it/new_split.c")' in committed_configure
    assert 'Object(NonMatching, "melee/it/old.c")' not in committed_configure
    assert "--no-require-protos" in committed_configure
    assert "default=True" in committed_configure
    assert 'config.wibo_tag = "1.0.0"' in committed_configure
    assert 'f"--config functionRelocDiffs={args.reloc_diffs}"' in committed_configure
    assert "def _purge_wrong_arch_wibo" in committed_configure
    assert "_purge_wrong_arch_wibo(config)" in committed_configure
    assert 'config.custom_build_steps = {"post-ok": []}' in committed_configure
    assert (
        _git(repo, "show", "HEAD:.github/workflows/build.yml").stdout
        == "upstream build v2\n"
    )
    assert (
        _git(repo, "show", "HEAD:.github/workflows/capabilities-drift.yml").stdout
        == "fork capability workflow\n"
    )
    assert (
        _git(repo, "show", "HEAD:tools/check/main.py").stdout
        == "upstream check v2\n"
    )
    assert not (repo / ".github" / "workflows" / "publish-packages.yml").exists()
    assert not (repo / ".github" / "packages" / "obsolete.txt").exists()
    committed_precommit = _git(repo, "show", "HEAD:.pre-commit-config.yaml").stdout
    assert "upstream-hook-v2" in committed_precommit
    assert "upstream-hook-v1" not in committed_precommit
    assert "stale-fork-hook" not in committed_precommit
    assert "id: capabilities-drift" in committed_precommit
    assert committed_precommit.count("exclude: ^(\\.claude/") == 3
    assert not stale_config.exists()
    assert personal_notes.read_text(encoding="utf-8") == "keep me untracked\n"
    assert _git(repo, "status", "--porcelain").stdout == "?? personal-notes.txt\n"
