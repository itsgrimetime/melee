from __future__ import annotations

import shlex
from pathlib import Path

from .models import ValidationCommand


def command_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def validation_commands_for_target(
    *,
    function: str,
    pcdump_path: str | Path | None,
    source_path: str | Path | None,
    force_phys: str,
    target_ig: int,
    blocker_ig: int | None,
    class_id: int,
) -> tuple[ValidationCommand, ...]:
    reg_prefix = "f" if class_id == 1 else "r"
    target_reg = f"{reg_prefix}{target_ig}"
    class_arg = f"--class {class_id} " if class_id != 0 else ""
    commands = [
        ValidationCommand(
            id=f"score-source-{class_id}-{target_ig}",
            purpose="score a candidate source edit against the target allocation",
            command=(
                "melee-agent debug target score-source CANDIDATE.c "
                f"-f {command_quote(function)} --target TARGET.yaml "
                "--checkdiff-guard --json"
            ),
        ),
    ]

    if pcdump_path is not None and source_path is not None and blocker_ig is not None:
        blocker_reg = f"{reg_prefix}{blocker_ig}"
        commands.append(
            ValidationCommand(
                id=f"lifetime-layout-{class_id}-{target_ig}-{blocker_ig}",
                purpose="probe source lifetime/layout changes for the target blocker pair",
                command=(
                    "melee-agent debug mutate lifetime-layout "
                    f"-f {command_quote(function)} "
                    f"--pcdump {command_quote(pcdump_path)} "
                    f"--source-file {command_quote(source_path)} "
                    f"--pairs {target_reg}/{blocker_reg} "
                    f"--transform-force-phys {command_quote(force_phys)} "
                    "--json"
                ),
            )
        )

    if pcdump_path is not None and source_path is not None:
        if blocker_ig is not None:
            blocker_reg = f"{reg_prefix}{blocker_ig}"
            order_target = f"{target_reg}<{blocker_reg}"
            commands.append(
                ValidationCommand(
                    id=f"select-order-{class_id}-{target_ig}-{blocker_ig}",
                    purpose="search select-order variants that move the target before the blocker",
                    command=(
                        "melee-agent debug select-order-search "
                        f"-f {command_quote(function)} "
                        f"{class_arg}"
                        f"--target {command_quote(order_target)} "
                        f"--force-phys {command_quote(force_phys)} "
                        f"--pcdump {command_quote(pcdump_path)} "
                        f"--source-file {command_quote(source_path)} --json"
                    ),
                )
            )
        commands.append(
            ValidationCommand(
                id=f"simplify-order-{class_id}-{target_ig}",
                purpose="probe simpler source order changes under the target allocation",
                command=(
                    "melee-agent debug mutate simplify-order "
                    f"-f {command_quote(function)} "
                    f"{class_arg}"
                    f"--force-phys {command_quote(force_phys)} "
                    f"--source-file {command_quote(source_path)} "
                    f"--pcdump {command_quote(pcdump_path)} --json"
                ),
            )
        )
        commands.append(
            ValidationCommand(
                id=f"inspect-diff-{class_id}-{target_ig}",
                purpose="inspect allocator dump differences after compiling a candidate",
                command=(
                    "melee-agent debug inspect diff "
                    f"{command_quote(pcdump_path)} CANDIDATE.pcdump.txt "
                    f"-f {command_quote(function)}"
                ),
            )
        )

    return tuple(commands)


__all__ = ["command_quote", "validation_commands_for_target"]
