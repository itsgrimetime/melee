"""Regression tests for mwcc_debug force-schedule overrides."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mwcc_debug_env_parse_buffers_are_static_for_zig_i386_build() -> None:
    text = (REPO_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text(
        encoding="utf-8",
    )
    for function in ("parse_iter_first_from_env", "parse_force_interfere_from_env"):
        match = re.search(
            rf"static void {function}\(void\)\n\{{(?P<body>.*?)\n\}}",
            text,
            flags=re.DOTALL,
        )
        assert match is not None
        body = match.group("body")
        assert "static char buf[MWCC_DEBUG_ENV_BUF_LEN];" in body
        assert "\n    char buf[MWCC_DEBUG_ENV_BUF_LEN];" not in body


def test_dump_local_help_exposes_force_schedule() -> None:
    result = runner.invoke(app, ["debug", "dump", "local", "--help"])

    assert result.exit_code == 0
    assert "--force-schedule" in result.stdout
    assert "--force-schedule-fn" in result.stdout
    assert "pin adjacent" in result.stdout
    assert "same-base load" in result.stdout
    assert "Non-load" in result.stdout
    assert "code-offset windows" in result.stdout
    assert "instruction scheduling" in result.stdout
    assert "DIAGNOSTIC-ONLY" in result.stdout


def test_dump_local_help_exposes_force_remat() -> None:
    result = runner.invoke(app, ["debug", "dump", "local", "--help"])

    assert result.exit_code == 0
    assert "--force-remat" in result.stdout
    assert "--force-remat-fn" in result.stdout
    assert "rematerialization" in result.stdout
    assert "copy|literal" in result.stdout
    assert "DIAGNOSTIC-ONLY" in result.stdout


def test_dump_remote_escapes_force_schedule_for_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/pl/plbonuslib.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/pl/plbonuslib.c",
            "--branch",
            "master",
            "--output",
            "-",
            "--force-schedule",
            "lwz:0x74>0x70",
            "--force-schedule-fn",
            "fn_8003F294",
        ],
    )

    assert result.exit_code == 0
    assert popen_calls
    remote_cmd = popen_calls[0][2]
    assert 'set "MWCC_DEBUG_FORCE_SCHEDULE=lwz:0x74>0x70"' in remote_cmd
    assert 'set "MWCC_DEBUG_FORCE_SCHEDULE_FUNCTION=fn_8003F294"' in remote_cmd


def test_dump_remote_escapes_force_remat_for_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/pl/plbonuslib.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/pl/plbonuslib.c",
            "--branch",
            "master",
            "--output",
            "-",
            "--force-remat",
            "0:62=copy",
            "--force-remat-fn",
            "fn_8003F294",
        ],
    )

    assert result.exit_code == 0
    assert popen_calls
    remote_cmd = popen_calls[0][2]
    assert 'set "MWCC_DEBUG_FORCE_REMAT=0:62=copy"' in remote_cmd
    assert 'set "MWCC_DEBUG_FORCE_REMAT_FUNCTION=fn_8003F294"' in remote_cmd


def test_dump_remote_force_remat_default_output_skips_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen_calls: list[list[str]] = []

    class FakeStdout:
        def __init__(self) -> None:
            self._chunks = [b"forced dump\n", b""]

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

    class FakePopen:
        def __init__(self, args, **_kwargs) -> None:
            popen_calls.append(args)
            self.stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_resolve_src_relative", lambda _path: "src/melee/pl/plbonuslib.c")
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("MWCC_DEBUG_TMP_ROOT", str(tmp_path / "scratch"))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/pl/plbonuslib.c",
            "--branch",
            "master",
            "--force-remat",
            "0:62=copy",
            "--force-remat-fn",
            "fn_8003F294",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert popen_calls
    assert not (
        tmp_path / "build" / "mwcc_debug_cache" / "melee" / "pl" / "plbonuslib.txt"
    ).exists()
    scratch_outputs = list((tmp_path / "scratch").glob("pcdump_remote_forced_*.txt"))
    assert len(scratch_outputs) == 1
    assert scratch_outputs[0].read_text(encoding="utf-8") == "forced dump\n"
    assert "forced run" in result.stderr


def test_dump_local_force_remat_reaches_child_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("debug compiler")
    env_capture = tmp_path / "env.txt"
    wibo = tmp_path / "fake-wibo.py"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['MELEE_TEST_FORCE_REMAT_ENV']).write_text(\n"
        "    os.environ.get('MWCC_DEBUG_FORCE_REMAT', '') + '\\n' +\n"
        "    os.environ.get('MWCC_DEBUG_FORCE_REMAT_FUNCTION', '') + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n', encoding='utf-8')\n"
        "if '-o' in sys.argv:\n"
        "    Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'object')\n"
    )
    wibo.chmod(0o755)
    output = tmp_path / "pcdump.out"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setenv("MELEE_TEST_FORCE_REMAT_ENV", str(env_capture))

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
            "--force-remat",
            "0:62=copy",
            "--force-remat-fn",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert env_capture.read_text(encoding="utf-8").splitlines() == [
        "0:62=copy",
        "fn_80000000",
    ]
    assert "force-* overrides are DIAGNOSTIC-ONLY" in result.stderr
    assert output.exists()


def test_permute_verify_passes_force_schedule_to_dump_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    better_call();\n}\n")

    run_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        run_calls.append([str(part) for part in cmd])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 96.7)
    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        lambda *args, **kwargs: (99.24117, None),
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
            "--force-schedule",
            "lwz:0x74>0x70",
            "--force-schedule-fn",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = __import__("json").loads(result.stdout)
    assert data["new_pct"] == 99.24117
    assert src_path.read_text() == original

    dump_cmd = run_calls[0]
    assert dump_cmd[:6] == ["python", "-m", "src.cli", "debug", "dump", "local"]
    assert "--no-cache-sync" in dump_cmd
    assert "--keep-obj" in dump_cmd
    assert "build/GALE01/src/melee/mn/sample.o" in dump_cmd
    assert "--force-schedule" in dump_cmd
    assert "lwz:0x74>0x70" in dump_cmd
    assert "--force-schedule-fn" in dump_cmd
    assert "fn_80000000" in dump_cmd


def test_mwcc_debug_force_schedule_c_helper_reorders_adjacent_same_base_loads(
    tmp_path: Path,
) -> None:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available")

    harness = tmp_path / "force_schedule_harness.c"
    exe = tmp_path / "force_schedule_harness"
    source = f"""
#define MWCC_DEBUG_TEST 1
#include "{(REPO_ROOT / "tools/mwcc_debug/mwcc_debug.c").as_posix()}"

typedef struct TestPCode {{
    PCode pc;
    const char *formatted;
}} TestPCode;

static void copy_string(char *dst, const char *src)
{{
    int i = 0;
    while (src[i]) {{
        dst[i] = src[i];
        i++;
    }}
    dst[i] = '\\0';
}}

static void test_formatoperands(void *pc, char *buf, int showBlocks)
{{
    (void)showBlocks;
    copy_string(buf, ((TestPCode *)pc)->formatted);
}}

static void link_nodes(PCodeBlock *block, TestPCode *a, TestPCode *b)
{{
    block->firstPCode = &a->pc;
    block->lastPCode = &b->pc;
    a->pc.prevPCode = 0;
    a->pc.nextPCode = &b->pc;
    b->pc.prevPCode = &a->pc;
    b->pc.nextPCode = 0;
}}

static void link_three(PCodeBlock *block, TestPCode *a, TestPCode *b, TestPCode *c)
{{
    block->firstPCode = &a->pc;
    block->lastPCode = &c->pc;
    a->pc.prevPCode = 0;
    a->pc.nextPCode = &b->pc;
    b->pc.prevPCode = &a->pc;
    b->pc.nextPCode = &c->pc;
    c->pc.prevPCode = &b->pc;
    c->pc.nextPCode = 0;
}}

int main(void)
{{
    if (pass_is_force_schedule_point("AFTER INSTRUCTION SCHEDULING") != 1)
        return 1;
    if (pass_is_force_schedule_point("FINAL CODE AFTER INSTRUCTION SCHEDULING") != 1)
        return 2;
    if (pass_is_force_schedule_point("AFTER REGISTER ALLOCATION") != 0)
        return 3;

    PCodeBlock block;
    TestPCode lower;
    TestPCode higher;
    TestPCode middle;
    TestPCode other_base;

    if (parse_force_schedule_rules_from_string("lwz:0x74>0x70", 14) != 1)
        return 10;
    if (g_force_schedule_rules[0].before_offset != 0x74)
        return 11;
    if (g_force_schedule_rules[0].after_offset != 0x70)
        return 12;

    lower.pc.op = 34;
    lower.formatted = "r6,112(r31)";
    higher.pc.op = 34;
    higher.formatted = "r7,116(r31)";
    link_nodes(&block, &lower, &higher);

    if (apply_force_schedule_to_block(&block) != 1)
        return 20;
    if (block.firstPCode != &higher.pc)
        return 21;
    if (higher.pc.nextPCode != &lower.pc)
        return 22;
    if (lower.pc.prevPCode != &higher.pc)
        return 23;
    if (block.lastPCode != &lower.pc)
        return 24;

    lower.pc.op = 34;
    lower.formatted = "r6,112(r31)";
    other_base.pc.op = 34;
    other_base.formatted = "r7,116(r30)";
    link_nodes(&block, &lower, &other_base);

    if (apply_force_schedule_to_block(&block) != 0)
        return 30;
    if (block.firstPCode != &lower.pc)
        return 31;

    if (parse_force_schedule_rules_from_string("lwz:0x74>0x70,lwz:0x1C>0x18", 29) != 2)
        return 40;
    lower.pc.op = 34;
    lower.formatted = "r6,24(r31)";
    higher.pc.op = 34;
    higher.formatted = "r7,28(r31)";
    link_nodes(&block, &lower, &higher);

    if (apply_force_schedule_to_block(&block) != 1)
        return 41;
    if (block.firstPCode != &higher.pc)
        return 42;

    if (parse_force_schedule_rules_from_string("lwz:0x1C>0x18", 14) != 1)
        return 50;
    lower.pc.op = 34;
    lower.formatted = "r6,24(r31)";
    middle.pc.op = 14;
    middle.formatted = "r9,r31,8";
    higher.pc.op = 34;
    higher.formatted = "r7,28(r31)";
    link_three(&block, &lower, &middle, &higher);

    if (apply_force_schedule_to_block(&block) != 1)
        return 51;
    if (block.firstPCode != &higher.pc)
        return 52;
    if (higher.pc.nextPCode != &middle.pc)
        return 53;
    if (middle.pc.prevPCode != &higher.pc)
        return 54;
    if (middle.pc.nextPCode != &lower.pc)
        return 55;
    if (lower.pc.prevPCode != &middle.pc)
        return 56;
    if (block.lastPCode != &lower.pc)
        return 57;

    return 0;
}}
"""
    harness.write_text(source)

    compile_proc = subprocess.run(
        [cc, "-std=c99", "-Werror", str(harness), "-o", str(exe)],
        capture_output=True,
        text=True,
    )
    assert compile_proc.returncode == 0, compile_proc.stderr

    run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run_proc.returncode == 0, run_proc.stderr


def test_mwcc_debug_force_remat_c_helper_toggles_alt_operand_flag(
    tmp_path: Path,
) -> None:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available")

    harness = tmp_path / "force_remat_harness.c"
    exe = tmp_path / "force_remat_harness"
    source = f"""
#define MWCC_DEBUG_TEST 1
#include "{(REPO_ROOT / "tools/mwcc_debug/mwcc_debug.c").as_posix()}"

static void test_formatoperands(void *pc, char *buf, int showBlocks)
{{
    (void)pc;
    (void)showBlocks;
    buf[0] = '\\0';
}}

static void set_string(char *dst, const char *src)
{{
    int i = 0;
    while (src[i]) {{
        dst[i] = src[i];
        i++;
    }}
    dst[i] = '\\0';
}}

int main(void)
{{
    IGNode node62;
    IGNode node63;
    IGNode node64;
    IGNode *ig[80];
    int i;

    for (i = 0; i < 80; i++)
        ig[i] = 0;

    node62.next = 0;
    node62.remat_record = 1;
    node62._x8 = 0;
    node62.ig_idx = 62;
    node62.degree = 0;
    node62.assignedReg = 21;
    node62.flags = 0;

    node63.next = 0;
    node63.remat_record = 1;
    node63._x8 = 0;
    node63.ig_idx = 63;
    node63.degree = 0;
    node63.assignedReg = 22;
    node63.flags = IG_FLAG_REMAT_ALT_OPERAND;

    node64.next = 0;
    node64.remat_record = 1;
    node64._x8 = 0;
    node64.ig_idx = 64;
    node64.degree = 0;
    node64.assignedReg = 23;
    node64.flags = 0;

    ig[62] = &node62;
    ig[63] = &node63;
    ig[64] = &node64;

    if (parse_force_remat_rules_from_string(
            "0:62=copy,0:63=literal,1:64=copy",
            sizeof("0:62=copy,0:63=literal,1:64=copy") - 1) != 3)
        return 1;
    g_force_remat_scope_fn_set = 0;
    if (apply_force_remat_rules_to_ig_array(0, ig, 80) != 2)
        return 2;
    if ((node62.flags & IG_FLAG_REMAT_ALT_OPERAND) == 0)
        return 3;
    if ((node63.flags & IG_FLAG_REMAT_ALT_OPERAND) != 0)
        return 4;
    if ((node64.flags & IG_FLAG_REMAT_ALT_OPERAND) != 0)
        return 5;

    if (parse_force_remat_rules_from_string(
            "0:62=literal", sizeof("0:62=literal") - 1) != 1)
        return 10;
    g_force_remat_scope_fn_set = 1;
    set_string(g_force_remat_scope_fn, "other_fn");
    g_current_function_set = 1;
    set_string(g_current_function, "fn_80000000");
    if (apply_force_remat_rules_to_ig_array(0, ig, 80) != 0)
        return 11;
    if ((node62.flags & IG_FLAG_REMAT_ALT_OPERAND) == 0)
        return 12;

    set_string(g_force_remat_scope_fn, "fn_80000000");
    if (apply_force_remat_rules_to_ig_array(0, ig, 80) != 1)
        return 13;
    if ((node62.flags & IG_FLAG_REMAT_ALT_OPERAND) != 0)
        return 14;

    return 0;
}}
"""
    harness.write_text(source)

    compile_proc = subprocess.run(
        [cc, "-std=c99", "-Werror", str(harness), "-o", str(exe)],
        capture_output=True,
        text=True,
    )
    assert compile_proc.returncode == 0, compile_proc.stderr

    run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run_proc.returncode == 0, run_proc.stderr


def test_mwcc_debug_long_force_override_parsers_are_not_silent(
    tmp_path: Path,
) -> None:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available")

    harness = tmp_path / "force_override_harness.c"
    exe = tmp_path / "force_override_harness"
    source = f"""
#define MWCC_DEBUG_TEST 1
#include "{(REPO_ROOT / "tools/mwcc_debug/mwcc_debug.c").as_posix()}"

static void test_formatoperands(void *pc, char *buf, int showBlocks)
{{
    (void)pc;
    (void)showBlocks;
    buf[0] = '\\0';
}}

static void append_char(char *buf, int *pos, char c)
{{
    buf[*pos] = c;
    *pos = *pos + 1;
    buf[*pos] = '\\0';
}}

static void append_uint(char *buf, int *pos, int value)
{{
    char digits[16];
    int n = 0;
    if (value == 0) {{
        append_char(buf, pos, '0');
        return;
    }}
    while (value > 0) {{
        digits[n++] = (char)('0' + (value % 10));
        value /= 10;
    }}
    while (n > 0)
        append_char(buf, pos, digits[--n]);
}}

static int build_iter_csv(char *buf, int count)
{{
    int i;
    int pos = 0;
    buf[0] = '\\0';
    for (i = 0; i < count; i++) {{
        if (i > 0) append_char(buf, &pos, ',');
        append_uint(buf, &pos, i);
    }}
    return pos;
}}

static int build_force_interfere_csv(char *buf, int count)
{{
    int i;
    int pos = 0;
    buf[0] = '\\0';
    for (i = 0; i < count; i++) {{
        if (i > 0) append_char(buf, &pos, ',');
        append_uint(buf, &pos, i);
        append_char(buf, &pos, '=');
        append_uint(buf, &pos, i + 1);
    }}
    return pos;
}}

int main(void)
{{
    char buf[12000];
    int len;

    if (MWCC_DEBUG_ENV_BUF_LEN < 4096)
        return 1;
    if (MAX_ITER_FIRST < 365)
        return 2;
    if (MAX_FORCE_INTERFERE < 67)
        return 3;

    len = build_iter_csv(buf, 365);
    if (parse_iter_first_values_from_string(buf, len) != 365)
        return 10;
    if (g_n_iter_first != 365)
        return 11;
    if (g_iter_first[0] != 0 || g_iter_first[364] != 364)
        return 12;
    if (g_iter_first_parse_overflow != 0)
        return 13;

    len = build_force_interfere_csv(buf, 67);
    if (parse_force_interfere_pairs_from_string(buf, len) != 67)
        return 20;
    if (g_n_force_interfere != 67)
        return 21;
    if (g_force_interfere[0].a != 0 || g_force_interfere[0].b != 1)
        return 22;
    if (g_force_interfere[66].a != 66 || g_force_interfere[66].b != 67)
        return 23;
    if (g_force_interfere_parse_overflow != 0)
        return 24;

    len = build_iter_csv(buf, MAX_ITER_FIRST + 1);
    if (parse_iter_first_values_from_string(buf, len) != MAX_ITER_FIRST)
        return 30;
    if (g_iter_first_parse_overflow == 0)
        return 31;

    len = build_force_interfere_csv(buf, MAX_FORCE_INTERFERE + 1);
    if (parse_force_interfere_pairs_from_string(buf, len) != MAX_FORCE_INTERFERE)
        return 40;
    if (g_force_interfere_parse_overflow == 0)
        return 41;

    return 0;
}}
"""
    harness.write_text(source)

    compile_proc = subprocess.run(
        [cc, "-std=c99", "-Werror", str(harness), "-o", str(exe)],
        capture_output=True,
        text=True,
    )
    assert compile_proc.returncode == 0, compile_proc.stderr

    run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run_proc.returncode == 0, run_proc.stderr
