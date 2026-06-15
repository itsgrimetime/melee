"""Regression tests for the mwcc_debug force-no-CSE IRO hook."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_validate_force_no_cse_normalizes_readable_specs() -> None:
    assert debug_cli._validate_force_no_cse("iro:0x1b7=0x1af,500") == "439=431,500"


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "iro:",
        "-1=2",
        "1=-2",
        "1=2=3",
        "1;2",
        "1 2",
    ],
)
def test_validate_force_no_cse_rejects_invalid_specs(spec: str) -> None:
    with pytest.raises(typer.BadParameter):
        debug_cli._validate_force_no_cse(spec)


def test_validate_force_no_cse_fn_rejects_scope_too_long_for_dll() -> None:
    with pytest.raises(typer.BadParameter, match="255-byte"):
        debug_cli._validate_force_no_cse_fn("f" * 256)


def test_dump_remote_passes_force_no_cse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    popen_calls: list[list[str]] = []

    class FakeStdout:
        def read(self, _size: int) -> bytes:
            return b""

    class FakePopen:
        stdout = FakeStdout()

        def __init__(self, args, **_kwargs) -> None:
            popen_calls.append(args)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/mn/mndiagram.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/mn/mndiagram.c",
            "--branch",
            "master",
            "--output",
            "-",
            "--force-no-cse",
            "iro:0x1b7=0x1af",
            "--force-no-cse-fn",
            "mnDiagram_80240D94",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert popen_calls
    remote_cmd = popen_calls[0][2]
    assert 'set "MWCC_DEBUG_FORCE_NO_CSE=439=431"' in remote_cmd
    assert 'set "MWCC_DEBUG_FORCE_NO_CSE_FUNCTION=mnDiagram_80240D94"' in remote_cmd


def test_dump_remote_passes_trace_cse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    popen_calls: list[list[str]] = []

    class FakeStdout:
        def read(self, _size: int) -> bytes:
            return b""

    class FakePopen:
        stdout = FakeStdout()

        def __init__(self, args, **_kwargs) -> None:
            popen_calls.append(args)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/mn/mndiagram.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/mn/mndiagram.c",
            "--branch",
            "master",
            "--output",
            "-",
            "--trace-cse",
            "--trace-cse-fn",
            "mnDiagram_80240D94",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert popen_calls
    remote_cmd = popen_calls[0][2]
    assert 'set "MWCC_DEBUG_TRACE_CSE=1"' in remote_cmd
    assert 'set "MWCC_DEBUG_TRACE_CSE_FUNCTION=mnDiagram_80240D94"' in remote_cmd


def test_dump_remote_rejects_overlong_force_no_cse_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **_kwargs) -> None:
            popen_calls.append(args)

    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/mn/mndiagram.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/mn/mndiagram.c",
            "--branch",
            "master",
            "--output",
            "-",
            "--force-no-cse",
            "439=431",
            "--force-no-cse-fn",
            "f" * 256,
        ],
    )

    assert result.exit_code == 2
    assert "255-byte" in result.stderr
    assert popen_calls == []


def test_dump_local_force_no_cse_reaches_child_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n", encoding="utf-8")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("debug compiler", encoding="utf-8")
    env_capture = tmp_path / "env.txt"
    wibo = tmp_path / "fake-wibo.py"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['MELEE_TEST_FORCE_NO_CSE_ENV']).write_text(\n"
        "    os.environ.get('MWCC_DEBUG_FORCE_NO_CSE', '') + '\\n' +\n"
        "    os.environ.get('MWCC_DEBUG_FORCE_NO_CSE_FUNCTION', '') + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n', encoding='utf-8')\n"
        "if '-o' in sys.argv:\n"
        "    Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'object')\n",
        encoding="utf-8",
    )
    wibo.chmod(0o755)
    output = tmp_path / "pcdump.out"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setenv("MELEE_TEST_FORCE_NO_CSE_ENV", str(env_capture))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "fn_80000000",
            "--output",
            str(output),
            "--force-no-cse",
            "iro:0x1b7=0x1af",
            "--force-no-cse-fn",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert env_capture.read_text(encoding="utf-8").splitlines() == [
        "439=431",
        "fn_80000000",
    ]
    assert "diagnostic overrides are DIAGNOSTIC-ONLY" in result.stderr
    assert output.exists()


def test_dump_local_trace_cse_uses_function_as_default_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n", encoding="utf-8")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("debug compiler", encoding="utf-8")
    env_capture = tmp_path / "trace-env.txt"
    wibo = tmp_path / "fake-wibo.py"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['MELEE_TEST_TRACE_CSE_ENV']).write_text(\n"
        "    os.environ.get('MWCC_DEBUG_TRACE_CSE', '') + '\\n' +\n"
        "    os.environ.get('MWCC_DEBUG_TRACE_CSE_FUNCTION', '') + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    wibo.chmod(0o755)
    output = tmp_path / "pcdump.out"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setenv("MELEE_TEST_TRACE_CSE_ENV", str(env_capture))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "fn_80000000",
            "--output",
            str(output),
            "--trace-cse",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert env_capture.read_text(encoding="utf-8").splitlines() == [
        "1",
        "fn_80000000",
    ]
    assert "diagnostic run" in result.stderr
    assert output.exists()


def test_dump_local_refuses_unscoped_force_no_cse_on_multi_function_tu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n{\n}\n\nvoid fn_80000004(void)\n{\n}\n",
        encoding="utf-8",
    )
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("debug compiler", encoding="utf-8")
    wibo = tmp_path / "fake-wibo.py"
    wibo.write_text("#!/usr/bin/env python3\nraise SystemExit(99)\n", encoding="utf-8")
    wibo.chmod(0o755)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--force-no-cse",
            "439=431",
        ],
    )

    assert result.exit_code == 2
    assert "refusing --force-no-cse without --force-no-cse-fn" in result.stderr


def test_mwcc_debug_force_no_cse_declares_real_common_subs_hook() -> None:
    text = (REPO_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text(
        encoding="utf-8",
    )

    assert "force-no-cse" in text
    assert "trace-cse" in text
    assert "hook_common_subs" in text
    assert "0x44DF00" in text
    assert "force_no_cse_current_function_name" in text
    assert "trace_cse_scope_matches" in text
    assert "MWCC_DEBUG_TRACE_CSE" in text
    assert "IRO_CommonSub: replaced node %d" in text
    assert "g_force_no_cse_scope_fn_truncated" in text
    assert "MWCC_DEBUG_FORCE_NO_CSE_FUNCTION" in text


def test_mwcc_debug_force_no_cse_c_helper_matches_selected_rules(
    tmp_path: Path,
) -> None:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available")

    harness = tmp_path / "force_no_cse_harness.c"
    exe = tmp_path / "force_no_cse_harness"
    source = f"""
#define MWCC_DEBUG_TEST 1
#include "{(REPO_ROOT / "tools/mwcc_debug/mwcc_debug.c").as_posix()}"

static void test_formatoperands(void *pc, char *buf, int showBlocks)
{{
    (void)pc;
    (void)showBlocks;
    buf[0] = '\\0';
}}

    int main(void)
    {{
        const char *spec = "439=431,500,0x20=0x21";
        if (parse_force_no_cse_rules_from_string(spec, 21) != 3) return 1;
    if (!force_no_cse_rule_matches(439, 431)) return 2;
    if (force_no_cse_rule_matches(439, 432)) return 3;
    if (!force_no_cse_rule_matches(500, 9)) return 4;
    if (!force_no_cse_rule_matches(32, 33)) return 5;
    return 0;
}}
"""
    harness.write_text(source, encoding="utf-8")
    compile_proc = subprocess.run(
        [cc, "-Wno-int-to-pointer-cast", str(harness), "-o", str(exe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compile_proc.returncode == 0, compile_proc.stderr
    run_proc = subprocess.run([str(exe)], check=False)
    assert run_proc.returncode == 0
