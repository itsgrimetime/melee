"""Tests for the dtk-backed objdump compatibility wrapper."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

from src.mwcc_debug.dtk_objdump import (
    convert_dtk_disasm_to_objdump,
    disassemble_object,
    find_melee_root,
    resolve_object_file,
    resolve_name_magic_target,
)


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
