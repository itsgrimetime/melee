"""Tests for the dtk-backed objdump compatibility wrapper."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.dtk_objdump import (
    DtkObjdumpError,
    convert_dtk_disasm_to_objdump,
    disassemble_object,
    find_melee_root,
    resolve_name_magic_target,
    resolve_object_file,
)

runner = CliRunner()


def _multi_function_dtk_text(*, suffix_immediate: int = 2) -> str:
    return textwrap.dedent(f"""\
        .fn prefix, global
        /* 80000000 00000034  38 60 00 00 */\tli r3, 0
        .endfn prefix

        .fn target_fn, global
        /* 80000004 00000038  3C 60 00 00 */\tlis r3, target_data@ha
        /* 80000008 0000003C  38 63 00 00 */\taddi r3, r3, target_data@l
        .endfn target_fn

        .fn suffix, global
        /* 8000000C 00000040  38 60 00 0{suffix_immediate} */\tli r3, {suffix_immediate}
        .endfn suffix
    """)


def test_convert_dtk_disasm_to_objdump_shape() -> None:
    dtk_text = textwrap.dedent("""\
        .include "macros.inc"

        # .text:0x0 | size: 0x8
        .fn fn_80000000, global
        /* 00000000 00000034  7C 08 02 A6 */\tmflr r0
        /* 00000004 00000038  3C 60 00 00 */\tlis r3, symbol@ha
    """)

    converted = convert_dtk_disasm_to_objdump(dtk_text)

    assert "0:\t7c 08 02 a6\tmflr r0" in converted
    assert "4:\t3c 60 00 00\tlis r3, symbol@ha" in converted


def test_convert_dtk_disasm_selects_exact_function_and_preserves_rows() -> None:
    converted = convert_dtk_disasm_to_objdump(
        _multi_function_dtk_text(),
        function="target_fn",
    )

    assert converted == (
        "80000004:\t3c 60 00 00\tlis r3, target_data@ha\n"
        "80000008:\t38 63 00 00\taddi r3, r3, target_data@l\n"
    )


def test_function_slice_ignores_unrelated_suffix_changes() -> None:
    target = convert_dtk_disasm_to_objdump(
        _multi_function_dtk_text(suffix_immediate=2),
        function="target_fn",
    )
    candidate = convert_dtk_disasm_to_objdump(
        _multi_function_dtk_text(suffix_immediate=7),
        function="target_fn",
    )

    assert candidate == target


def test_unfiltered_multi_function_conversion_remains_compatible() -> None:
    converted = convert_dtk_disasm_to_objdump(_multi_function_dtk_text())

    assert converted == (
        "80000000:\t38 60 00 00\tli r3, 0\n"
        "80000004:\t3c 60 00 00\tlis r3, target_data@ha\n"
        "80000008:\t38 63 00 00\taddi r3, r3, target_data@l\n"
        "8000000c:\t38 60 00 02\tli r3, 2\n"
    )


@pytest.mark.parametrize(
    ("dtk_text", "error"),
    [
        (_multi_function_dtk_text(), "not found"),
        (
            _multi_function_dtk_text()
            + ".fn target_fn, global\n"
            + "/* 80000010 00000044  4E 80 00 20 */\tblr\n"
            + ".endfn target_fn\n",
            "appears 2 times",
        ),
        (
            ".fn broken, global\n"
            "/* 80000000 00000034  4E 80 00 20 */\tblr\n",
            "missing .endfn",
        ),
        (
            ".fn broken, global\n"
            "/* 80000000 00000034  4E 80 00 20 */\tblr\n"
            ".endfn another\n",
            "mismatched .endfn",
        ),
        (
            ".fn broken, global\n"
            ".endfn broken\n",
            "no instruction rows",
        ),
    ],
)
def test_convert_dtk_disasm_function_selector_fails_closed(
    dtk_text: str,
    error: str,
) -> None:
    function = "missing" if error == "not found" else (
        "target_fn" if "appears" in error else "broken"
    )

    with pytest.raises(DtkObjdumpError, match=error):
        convert_dtk_disasm_to_objdump(dtk_text, function=function)


def test_find_melee_root_prefers_melee_root_env(tmp_path, monkeypatch) -> None:
    remote_melee = tmp_path / "permuter-work" / "melee"
    dtk = remote_melee / "build" / "tools" / "dtk"
    dtk.parent.mkdir(parents=True)
    dtk.write_text("dtk\n")

    remote_run = (
        tmp_path
        / "permuter-work"
        / "decomp-permuter"
        / "remote-runs"
        / "job-1"
        / "nonmatchings"
        / "fn_80000000"
    )
    remote_run.mkdir(parents=True)
    monkeypatch.chdir(remote_run)
    monkeypatch.setenv("MELEE_ROOT", str(remote_melee))

    assert find_melee_root() == Path(remote_melee)


def test_resolve_object_file_uses_object_root_for_remote_run_relative_path(
    tmp_path,
    monkeypatch,
) -> None:
    perm_root = tmp_path / "permuter-work" / "decomp-permuter"
    obj = (
        perm_root
        / "remote-runs"
        / "job-1"
        / "nonmatchings"
        / "fn_80000000"
        / "target.o"
    )
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b"obj")
    monkeypatch.chdir(tmp_path / "permuter-work")

    resolved = resolve_object_file(
        Path("remote-runs/job-1/nonmatchings/fn_80000000/target.o"),
        object_root=perm_root,
    )

    assert resolved == obj


def test_resolve_name_magic_target_prefers_sibling_target(tmp_path: Path) -> None:
    base = tmp_path / "nonmatchings" / "fn_80000000" / "base.o"
    target = base.with_name("target.o")
    target.parent.mkdir(parents=True)
    base.write_bytes(b"base")
    target.write_bytes(b"target")

    assert resolve_name_magic_target(base, tmp_path) == target
    assert resolve_name_magic_target(target, tmp_path) is None


def test_resolve_name_magic_target_maps_build_src_to_obj(tmp_path: Path) -> None:
    root = tmp_path / "melee"
    base = root / "build" / "GALE01" / "src" / "melee" / "lb" / "lbcobj.o"
    target = root / "build" / "GALE01" / "obj" / "melee" / "lb" / "lbcobj.o"
    base.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    base.write_bytes(b"base")
    target.write_bytes(b"target")

    assert resolve_name_magic_target(base, root) == target


def test_disassemble_object_applies_name_magic_to_temp_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "melee"
    dtk = root / "build" / "tools" / "dtk"
    dtk.parent.mkdir(parents=True)
    dtk.write_text("dtk\n")

    base = tmp_path / "nonmatchings" / "fn_80000000" / "base.o"
    target = base.with_name("target.o")
    base.parent.mkdir(parents=True)
    base.write_bytes(b"base")
    target.write_bytes(b"target")

    calls: dict[str, Path] = {}

    def fake_apply_name_magic_auto(work_o: Path, target_o: Path):
        calls["work_o"] = work_o
        calls["target_o"] = target_o
        work_o.write_bytes(b"renamed")
        return SimpleNamespace(renames=[("@1", "named")])

    def fake_run(cmd, **kwargs):
        obj_path = Path(cmd[3])
        out_path = Path(cmd[4])
        calls["disassembled"] = obj_path
        assert obj_path.read_bytes() == b"renamed"
        out_path.write_text(
            "/* 00000000 00000000  3C 60 00 00 */\tlis r3, named@ha\n"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "src.mwcc_debug.o_rewriter.apply_name_magic_auto",
        fake_apply_name_magic_auto,
    )
    monkeypatch.setattr("src.mwcc_debug.dtk_objdump.subprocess.run", fake_run)

    disassembly = disassemble_object(base, melee_root=root)

    assert "named@ha" in disassembly
    assert calls["target_o"] == target
    assert calls["work_o"] != base
    assert calls["disassembled"] == calls["work_o"]
    assert base.read_bytes() == b"base"


def test_dtk_objdump_cli_passes_function_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    obj = tmp_path / "candidate.o"
    obj.write_bytes(b"obj")
    calls: dict[str, object] = {}

    def fake_disassemble_object(o_file: Path, **kwargs: object) -> str:
        calls["o_file"] = o_file
        calls.update(kwargs)
        return "80000004:\t4e 80 00 20\tblr\n"

    monkeypatch.setattr(
        "src.mwcc_debug.dtk_objdump.disassemble_object",
        fake_disassemble_object,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "dtk-objdump",
            "--function",
            "target_fn",
            str(obj),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["o_file"] == obj
    assert calls["function"] == "target_fn"


def test_dtk_objdump_cli_reports_missing_function(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    obj = tmp_path / "candidate.o"
    obj.write_bytes(b"obj")

    def fake_disassemble_object(*args: object, **kwargs: object) -> str:
        raise DtkObjdumpError(
            "requested function 'missing' not found in dtk disassembly"
        )

    monkeypatch.setattr(
        "src.mwcc_debug.dtk_objdump.disassemble_object",
        fake_disassemble_object,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "dtk-objdump",
            "--function",
            "missing",
            str(obj),
        ],
    )

    assert result.exit_code == 2
    assert "requested function 'missing' not found" in result.output
