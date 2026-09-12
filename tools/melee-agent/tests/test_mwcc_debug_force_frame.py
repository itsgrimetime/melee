from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.mwcc_debug.force_frame import (
    InstructionBytePatch,
    apply_function_byte_patches,
    derive_force_frame_patch_plan,
)


def test_derive_force_frame_patch_plan_from_stack_layout_diff() -> None:
    payload = {
        "classification": {"primary": "stack-layout"},
        "target_asm": [
            "<gm_801A9DD0>:",
            "+014: 94 21 ff 70 \tstwu    r1,-144(r1)",
            "+05c: R_PPC_EMB_SDA21\tgm_804DAAB0",
            "+060: 91 01 00 24 \tstw     r8,36(r1)",
            "+064: 38 60 00 01 \tli      r3,1",
            "+13c: 38 81 00 38 \taddi    r4,r1,56",
            "+1f0: 38 21 00 90 \taddi    r1,r1,144",
        ],
        "current_asm": [
            "<gm_801A9DD0>:",
            "+014: 94 21 ff 68 \tstwu    r1,-152(r1)",
            "+05c: R_PPC_EMB_SDA21\t@146",
            "+060: 91 01 00 28 \tstw     r8,40(r1)",
            "+064: 38 60 00 02 \tli      r3,2",
            "+13c: 38 81 00 3c \taddi    r4,r1,60",
            "+1f0: 38 21 00 98 \taddi    r1,r1,152",
        ],
    }

    plan = derive_force_frame_patch_plan(payload)

    assert [(p.offset, p.expected_bytes.hex(), p.replacement_bytes.hex()) for p in plan.byte_patches] == [
        (0x14, "9421ff68", "9421ff70"),
        (0x60, "91010028", "91010024"),
        (0x13C, "3881003c", "38810038"),
        (0x1F0, "38210098", "38210090"),
    ]
    assert [(r.old_name, r.new_name) for r in plan.symbol_renames] == [
        ("@146", "gm_804DAAB0"),
    ]


def _powerpc_as() -> str | None:
    path = shutil.which("powerpc-eabi-as")
    if path:
        return path
    fallback = Path("/opt/devkitpro/devkitPPC/bin/powerpc-eabi-as")
    if fallback.exists():
        return str(fallback)
    return None


@pytest.mark.skipif(_powerpc_as() is None, reason="requires powerpc-eabi-as")
def test_apply_function_byte_patches_rewrites_function_bytes(tmp_path: Path) -> None:
    asm_path = tmp_path / "sample.s"
    obj_path = tmp_path / "sample.o"
    asm_path.write_text(
        ".section .text\n"
        ".globl fn_80000000\n"
        ".type fn_80000000,@function\n"
        "fn_80000000:\n"
        "  stwu 1,-152(1)\n"
        "  addi 1,1,152\n"
        ".size fn_80000000, .-fn_80000000\n"
    )
    subprocess.run([_powerpc_as(), "-o", str(obj_path), str(asm_path)], check=True)

    patches = [
        InstructionBytePatch(
            offset=0,
            expected_bytes=bytes.fromhex("9421ff68"),
            replacement_bytes=bytes.fromhex("9421ff70"),
            mnemonic="stwu",
            current_operands="r1,-152(r1)",
            target_operands="r1,-144(r1)",
        ),
        InstructionBytePatch(
            offset=4,
            expected_bytes=bytes.fromhex("38210098"),
            replacement_bytes=bytes.fromhex("38210090"),
            mnemonic="addi",
            current_operands="r1,r1,152",
            target_operands="r1,r1,144",
        ),
    ]

    assert apply_function_byte_patches(obj_path, "fn_80000000", patches) == 2
    rewritten = obj_path.read_bytes()
    assert bytes.fromhex("9421ff70") in rewritten
    assert bytes.fromhex("38210090") in rewritten
    assert bytes.fromhex("9421ff68") not in rewritten
    assert bytes.fromhex("38210098") not in rewritten
