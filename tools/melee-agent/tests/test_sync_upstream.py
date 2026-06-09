"""Regression tests for tools/workflow/sync-upstream.sh."""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path


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
            # Default is "functionRelocDiffs=none", which is most lenient
            # "--config functionRelocDiffs=data_value",
        ]

        if args.mode == "configure":
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


def test_sync_upstream_preserves_upstream_configure_and_clears_config_json(
    tmp_path: Path,
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
    _git(upstream_work, "add", "configure.py")
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
    _git(
        repo,
        "add",
        "tools/workflow/sync-upstream.sh",
        "configure.py",
    )
    _git(repo, "commit", "-m", "fork tooling")

    stale_config = repo / "build" / "GALE01" / "config.json"
    stale_config.parent.mkdir(parents=True)
    stale_config.write_text('{"version": "v1.8.3", "units": []}\n', encoding="utf-8")
    assert "?? build/" in _git(repo, "status", "--porcelain").stdout

    (upstream_work / "configure.py").write_text(
        _upstream_configure('Object(NonMatching, "melee/it/new_split.c")'),
        encoding="utf-8",
    )
    _git(upstream_work, "add", "configure.py")
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
    assert "def _purge_wrong_arch_wibo" in committed_configure
    assert "_purge_wrong_arch_wibo(config)" in committed_configure
    assert not stale_config.exists()
    assert _git(repo, "status", "--porcelain").stdout == ""
