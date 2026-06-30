"""`debug intervene ...` — backend-backed allocator interventions.

Carved out of cli/debug/__init__.py. Contains the single intervene command
handler (coalesce) and its group-private helper (_run_intervention_dump).

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via call-time
(deferred) ``from src.cli.debug import ...`` imports inside the function
bodies -- a load-time import would create a cycle (__init__ imports this
module) and would also break ``monkeypatch.setattr(debug_cli, ...)``
semantics, since the patched name must resolve against __init__ at call time.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import (
    Annotated,
    Optional,
)

import typer

from ...mwcc_debug.temp_scratch import mkdtemp as mwcc_debug_mkdtemp

intervene_app = typer.Typer(
    help="Run backend-backed allocator interventions and report allocator deltas."
)

__all__: list[str] = ["_run_intervention_dump"]


@intervene_app.command(name="coalesce")
def intervene_coalesce_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to scope the backend coalesce intervention to.",
        ),
    ],
    force: Annotated[
        Optional[str],
        typer.Option(
            "--force",
            help="Force one coalesce pair, e.g. r43=r40.",
        ),
    ] = None,
    block: Annotated[
        Optional[str],
        typer.Option(
            "--block",
            help="Block one natural coalesce pair by un-coalescing the left "
                 "virtual, e.g. r43=r40 emits MWCC_DEBUG_FORCE_COALESCE=43=43.",
        ),
    ] = None,
    trace_copy_json: Annotated[
        Optional[Path],
        typer.Option(
            "--trace-copy-json",
            help=(
                "trace-copy --json report to derive a force pair as "
                "copy destination=rooted to source, preserving register class."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to compile when pcdumps are not both supplied.",
        ),
    ] = None,
    baseline_pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--baseline-pcdump",
            help="Existing natural pcdump. If omitted, compile --source-file.",
        ),
    ] = None,
    intervention_pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--intervention-pcdump",
            help="Existing forced pcdump. If omitted, compile --source-file "
                 "with the backend coalesce hook.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Compile path for missing pcdumps: local or remote.",
        ),
    ] = "local",
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help="Directory for generated baseline/intervention pcdumps.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-dump compile timeout in seconds.",
        ),
    ] = 120,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Remote host when --mode remote is used.",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Forward --no-pull to debug dump remote.",
        ),
    ] = False,
    baseline_match_percent: Annotated[
        Optional[float],
        typer.Option(
            "--baseline-match-percent",
            help="Optional externally measured baseline real match percent.",
        ),
    ] = None,
    intervention_match_percent: Annotated[
        Optional[float],
        typer.Option(
            "--intervention-match-percent",
            help="Optional externally measured intervention real match percent.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Run/report a scoped coalesce intervention backed by the mwcc_debug DLL.

    The implemented block slice uses the existing backend hook:
    `MWCC_DEBUG_FORCE_COALESCE=virt=virt`. That value is passed through
    `debug dump local|remote --force-coalesce ... --force-coalesce-fn FN`,
    so the compiler/DLL, not this wrapper, changes allocator state.
    """
    from ...mwcc_debug.allocator_intervention import (
        CoalesceInterventionSpec,
        analyze_coalesce_intervention,
        parse_coalesce_pair_with_class,
        render_coalesce_intervention_text,
    )
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _load_trace_copy_repair_target,
        _resolve_existing_cli_file,
    )

    explicit_actions = sum([force is not None, block is not None])
    if trace_copy_json is None and explicit_actions != 1:
        typer.echo(
            "provide exactly one of --force, --block, or --trace-copy-json.",
            err=True,
        )
        raise typer.Exit(2)
    if trace_copy_json is not None and explicit_actions != 0:
        typer.echo(
            "--trace-copy-json is mutually exclusive with --force/--block.",
            err=True,
        )
        raise typer.Exit(2)
    if mode not in {"local", "remote"}:
        typer.echo("--mode must be either local or remote.", err=True)
        raise typer.Exit(2)

    target_source = "--force" if force is not None else "--block"
    if trace_copy_json is not None:
        trace_target = _load_trace_copy_repair_target(
            trace_copy_json,
            function=function,
        )
        virt = trace_target["to_virtual"]
        root = trace_target["from_virtual"]
        class_id = 1 if trace_target.get("register_class") == "fpr" else 0
        action = "force"
        target_source = "trace-copy-json"
    else:
        raw_pair = force if force is not None else block
        assert raw_pair is not None
        try:
            virt, root, class_id = parse_coalesce_pair_with_class(raw_pair)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2)
        action = "force" if force is not None else "block"
    spec = CoalesceInterventionSpec(
        action=action,
        virt=virt,
        root=root,
        class_id=class_id,
    )

    if baseline_pcdump is not None and not baseline_pcdump.is_file():
        raise typer.BadParameter(f"baseline pcdump not found: {baseline_pcdump}")
    if intervention_pcdump is not None and not intervention_pcdump.is_file():
        raise typer.BadParameter(
            f"intervention pcdump not found: {intervention_pcdump}"
        )

    if baseline_pcdump is None or intervention_pcdump is None:
        if source_file is None:
            typer.echo(
                "--source-file is required when either pcdump is omitted.",
                err=True,
            )
            raise typer.Exit(2)
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        run_dir = output_dir or mwcc_debug_mkdtemp(prefix="melee_intervene_")
        run_dir.mkdir(parents=True, exist_ok=True)
        if baseline_pcdump is None:
            baseline_pcdump = run_dir / f"{function}.baseline.pcdump.txt"
            _run_intervention_dump(
                label="baseline",
                source_file=source_file,
                output=baseline_pcdump,
                function=function,
                mode=mode,
                timeout=timeout,
                host=host,
                no_pull=no_pull,
                spec=None,
            )
        if intervention_pcdump is None:
            intervention_pcdump = run_dir / f"{function}.coalesce-intervention.pcdump.txt"
            _run_intervention_dump(
                label="intervention",
                source_file=source_file,
                output=intervention_pcdump,
                function=function,
                mode=mode,
                timeout=timeout,
                host=host,
                no_pull=no_pull,
                spec=spec,
            )

    assert baseline_pcdump is not None
    assert intervention_pcdump is not None
    try:
        report = analyze_coalesce_intervention(
            baseline_pcdump.read_text(encoding="utf-8", errors="replace"),
            intervention_pcdump.read_text(encoding="utf-8", errors="replace"),
            function=function,
            spec=spec,
            baseline_match_percent=baseline_match_percent,
            intervention_match_percent=intervention_match_percent,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    if json_out:
        payload = report.to_dict()
        payload["target_source"] = target_source
        print(json.dumps(payload, indent=2))
        return
    if target_source == "trace-copy-json":
        print("target source: trace-copy-json")
    print(render_coalesce_intervention_text(report))
    print(f"baseline pcdump: {baseline_pcdump}")
    print(f"intervention pcdump: {intervention_pcdump}")


def _run_intervention_dump(
    *,
    label: str,
    source_file: Path,
    output: Path,
    function: str,
    mode: str,
    timeout: int,
    host: str,
    no_pull: bool,
    spec,
) -> None:
    from src.cli.debug import DEFAULT_MELEE_ROOT  # noqa: PLC0415

    cmd = [
        "python",
        "-m",
        "src.cli",
        "debug",
        "dump",
        mode,
        str(source_file),
        "--output",
        str(output),
    ]
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parents[3]
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root)
        if not existing_pythonpath
        else str(package_root) + os.pathsep + existing_pythonpath
    )
    if mode == "local":
        cmd.extend(["--no-cache-sync", "--function", function])
        env["MWCC_DEBUG_HANG_TIMEOUT"] = str(timeout)
    else:
        cmd.extend(["--timeout", str(timeout)])
        cmd.extend(["--host", host])
        if no_pull:
            cmd.append("--no-pull")
    if spec is not None:
        cmd.extend([
            "--force-coalesce",
            spec.backend_value,
            "--force-coalesce-fn",
            function,
        ])
        if spec.class_id != 0:
            cmd.extend(["--force-coalesce-class", str(spec.class_id)])

    proc = subprocess.run(
        cmd,
        cwd=DEFAULT_MELEE_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        env_hint = ""
        if spec is not None:
            env_hint = (
                " ("
                + " ".join(f"{key}={value}" for key, value in spec.backend_env.items())
                + ")"
            )
        typer.echo(f"{label} compile failed{env_hint}", err=True)
        if proc.stderr:
            typer.echo(proc.stderr, err=True, nl=False)
        if proc.stdout:
            typer.echo(proc.stdout, err=True, nl=False)
        raise typer.Exit(proc.returncode)
    if not output.exists():
        typer.echo(f"{label} compile completed without writing {output}", err=True)
        raise typer.Exit(4)
