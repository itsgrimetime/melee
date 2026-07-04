from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .commands import command_quote
from .models import ValidationCommand
from .targets import parse_force_phys_spec

ValidationRunner = Callable[[list[str], int], dict[str, object]]


def build_remote_validation_plan(
    *,
    function: str,
    force_phys: str,
    timeout: int,
    campaign_dir: Path,
    source_candidates: list[Path],
    target_file: Path | None = None,
) -> tuple[ValidationCommand, ...]:
    target_path = (
        target_file
        if target_file is not None
        else campaign_dir / f"{_safe_filename(function)}.force-phys.target.yaml"
    )
    commands: list[ValidationCommand] = []
    candidates = source_candidates or [Path("CANDIDATE.c")]
    for index, candidate in enumerate(candidates, start=1):
        output_path = campaign_dir / f"{candidate.stem}.pcdump.txt"
        commands.append(
            ValidationCommand(
                id=f"remote-score-source-{index}",
                purpose=(
                    "emit a remote-fallback score-source validation command "
                    f"for force-phys {force_phys}"
                ),
                command=(
                    "melee-agent debug target score-source "
                    f"{command_quote(candidate)} "
                    f"-f {command_quote(function)} "
                    f"--target {command_quote(target_path)} "
                    "--json --retain-pcdump --checkdiff-guard "
                    "--remote-fallback "
                    f"--pcdump-output {command_quote(output_path)} "
                    f"--timeout {timeout}"
                ),
                mode="emit",
            )
        )
    return tuple(commands)


def materialize_force_phys_target_spec(
    *,
    function: str,
    class_id: int,
    force_phys: str,
    baseline_dump: Path,
    output_dir: Path,
) -> Path:
    import yaml  # type: ignore

    target_set = parse_force_phys_spec(force_phys, default_class_id=class_id)
    force_phys_map: dict[int, int] = {}
    for target in target_set.targets:
        if target.class_id != class_id:
            raise ValueError(
                f"force-phys target {target.ig_id} has class {target.class_id}, "
                f"expected class {class_id}"
            )
        force_phys_map[target.ig_id] = target.expected_phys
    if not force_phys_map:
        raise ValueError("force-phys spec must contain at least one target")

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / f"{_safe_filename(function)}.force-phys.target.yaml"
    target_path.write_text(
        yaml.safe_dump(
            {
                "function": function,
                "class_id": class_id,
                "baseline_dump": str(baseline_dump),
                "force_phys": force_phys_map,
                "coalesce_preservation": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target_path


def run_quick_validation(
    *,
    function: str,
    target_file: Path,
    source_candidates: list[Path],
    timeout: int,
    runner: ValidationRunner | None = None,
) -> list[dict[str, object]]:
    active_runner = runner or _subprocess_runner
    results: list[dict[str, object]] = []
    for candidate in source_candidates:
        argv = [
            "melee-agent",
            "debug",
            "target",
            "score-source",
            str(candidate),
            "-f",
            function,
            "--target",
            str(target_file),
            "--json",
            "--retain-pcdump",
            "--checkdiff-guard",
            "--timeout",
            str(timeout),
        ]
        proc = active_runner(argv, timeout)
        payload = _json_payload(proc.get("stdout", ""))
        status = _score_source_status(payload, proc)
        results.append(
            {
                "candidate": str(candidate),
                "status": status,
                "argv": argv,
                "returncode": proc.get("returncode"),
                "stdout": proc.get("stdout", ""),
                "stderr": proc.get("stderr", ""),
                "target_score": _mapping(payload.get("target_score")),
                "force_phys_score": _mapping(payload.get("force_phys_score")),
                "checkdiff_guard": _mapping(payload.get("checkdiff_guard")),
                "structural_guard": _mapping(payload.get("structural_guard")),
                "raw_score": payload,
            }
        )
    return results


def run_bounded_validation(
    *,
    function: str,
    force_phys: str,
    pcdump_path: Path | None,
    source_path: Path | None,
    timeout: int,
    max_candidates: int,
    direct_blockers: list[tuple[int, int, int]] | None = None,
    runner: ValidationRunner | None = None,
) -> list[dict[str, object]]:
    if pcdump_path is None or source_path is None:
        return []

    active_runner = runner or _subprocess_runner
    direct_blockers = direct_blockers or []
    commands: list[tuple[str, list[str]]] = []
    lifetime_layout_argv = _lifetime_layout_argv(
        function=function,
        force_phys=force_phys,
        pcdump_path=pcdump_path,
        source_path=source_path,
        timeout=timeout,
        max_candidates=max_candidates,
        direct_blockers=direct_blockers,
    )
    if lifetime_layout_argv is not None:
        commands.append(("lifetime-layout", lifetime_layout_argv))
    commands.append(
        (
            "simplify-order",
            [
                "melee-agent",
                "debug",
                "mutate",
                "simplify-order",
                "-f",
                function,
                "--force-phys",
                force_phys,
                "--source-file",
                str(source_path),
                "--pcdump",
                str(pcdump_path),
                "--max-candidates",
                str(max_candidates),
                "--timeout",
                str(timeout),
                "--json",
            ],
        ),
    )
    for class_id, target_ig, blocker_ig in direct_blockers:
        reg_prefix = "f" if class_id == 1 else "r"
        argv = [
            "melee-agent",
            "debug",
            "select-order-search",
            "-f",
            function,
            "--target",
            f"{reg_prefix}{target_ig}<{reg_prefix}{blocker_ig}",
            "--force-phys",
            force_phys,
            "--pcdump",
            str(pcdump_path),
            "--source-file",
            str(source_path),
            "--max-probes",
            str(max_candidates),
            "--timeout",
            str(timeout),
            "--json",
        ]
        if class_id == 1:
            argv[5:5] = ["--class", "1"]
        commands.append((f"select-order-{class_id}-{target_ig}-{blocker_ig}", argv))

    results: list[dict[str, object]] = []
    for workflow, argv in commands:
        proc = active_runner(argv, timeout)
        payload = _json_payload(proc.get("stdout", ""))
        results.append(
            {
                "candidate": workflow,
                "status": _bounded_workflow_status(workflow, payload, proc),
                "argv": argv,
                "returncode": proc.get("returncode"),
                "stdout": proc.get("stdout", ""),
                "stderr": proc.get("stderr", ""),
                "raw_score": payload,
            }
        )
    return results


def _lifetime_layout_argv(
    *,
    function: str,
    force_phys: str,
    pcdump_path: Path,
    source_path: Path,
    timeout: int,
    max_candidates: int,
    direct_blockers: list[tuple[int, int, int]],
) -> list[str] | None:
    target_classes = {
        target.class_id
        for target in parse_force_phys_spec(force_phys, default_class_id=0).targets
    }
    pair_arg: str | None = None
    if direct_blockers:
        blocker_classes = {class_id for class_id, _target, _blocker in direct_blockers}
        if len(target_classes) != 1 or blocker_classes != target_classes:
            return None
        class_id = next(iter(blocker_classes))
        prefix = "f" if class_id == 1 else "r"
        pair_arg = ",".join(
            f"{prefix}{target_ig}/{prefix}{blocker_ig}"
            for _class_id, target_ig, blocker_ig in direct_blockers
        )
    elif target_classes != {0}:
        return None

    argv = [
        "melee-agent",
        "debug",
        "mutate",
        "lifetime-layout",
        "-f",
        function,
        "--pcdump",
        str(pcdump_path),
        "--source-file",
        str(source_path),
        "--compile-probes",
        "--max-probes",
        str(max_candidates),
        "--timeout",
        str(timeout),
        "--transform-force-phys",
        force_phys,
        "--json",
    ]
    if pair_arg is not None:
        argv[10:10] = ["--pairs", pair_arg]
    return argv


def _bounded_workflow_status(
    workflow: str,
    payload: dict[str, Any],
    proc: dict[str, object],
) -> str:
    if int(proc.get("returncode") or 0) != 0:
        return "rejected"
    if workflow == "lifetime-layout":
        return _lifetime_layout_status(payload)
    return "partial_progress"


def _lifetime_layout_status(payload: dict[str, Any]) -> str:
    best_hits = 0
    for variant in _list_of_mappings(payload.get("variants")):
        score = _mapping(variant.get("target_score"))
        if not score:
            continue
        hits = _int_value(score.get("hits"))
        if hits == 0:
            hits = _int_value(score.get("matched"))
        targeted = _int_value(score.get("targeted"))
        best_hits = max(best_hits, hits)
        if targeted > 0 and hits >= targeted:
            return "full_target_match"

    terminal = _mapping(payload.get("terminal_summary"))
    proof = _mapping(terminal.get("force_phys_terminal_proof"))
    if not proof and terminal.get("kind") == "lifetime-layout-force-phys-terminal-proof":
        proof = terminal
    best_hits = max(best_hits, _int_value(proof.get("best_hits")))
    return "partial_progress" if best_hits > 0 else "rejected"


def _subprocess_runner(argv: list[str], timeout: int) -> dict[str, object]:
    subprocess_timeout = timeout if timeout > 0 else None
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or str(exc),
        }
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _score_source_status(
    payload: dict[str, Any],
    proc: dict[str, object],
) -> str:
    if int(proc.get("returncode") or 0) != 0:
        return "rejected"

    target_score = _mapping(payload.get("target_score"))
    force_phys_score = _mapping(payload.get("force_phys_score"))
    if force_phys_score.get("structural_rejection") is True:
        return "rejected"
    for guard_key in ("checkdiff_guard", "structural_guard"):
        guard = _mapping(payload.get(guard_key))
        if guard and guard.get("accepted") is False:
            return "rejected"

    targeted = _int_value(target_score.get("targeted"))
    matched = _int_value(target_score.get("matched"))
    force_hits = _int_value(force_phys_score.get("force_phys_hits"))
    virtuals = _mapping(target_score.get("virtuals"))
    virtual_values = [
        virtual for virtual in virtuals.values() if isinstance(virtual, dict)
    ]
    if any(
        virtual.get("baseline_matched") is True
        and virtual.get("matched") is not True
        for virtual in virtual_values
    ):
        return "rejected"

    all_virtuals_matched = bool(virtual_values) and all(
        virtual.get("matched") is True for virtual in virtual_values
    )
    if targeted > 0 and matched >= targeted and force_hits >= targeted:
        if not virtual_values or all_virtuals_matched:
            return "full_target_match"

    improved_virtual = any(
        virtual.get("matched") is True
        and virtual.get("baseline_matched") is not True
        for virtual in virtual_values
    )
    if matched > 0 or force_hits > 0 or improved_virtual:
        return "partial_progress"
    return "rejected"


def _json_payload(stdout: object) -> dict[str, Any]:
    if not isinstance(stdout, str) or not stdout.strip():
        return {}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                break
            except json.JSONDecodeError:
                continue
        else:
            return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "target"


__all__ = [
    "ValidationRunner",
    "build_remote_validation_plan",
    "materialize_force_phys_target_spec",
    "run_quick_validation",
    "run_bounded_validation",
]
