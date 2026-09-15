"""Top-level ``debug`` commands carved out of cli/debug/__init__.py.

These four handlers are registered directly on ``debug_app`` (NOT under a
subgroup): ``suggest-schedule-source`` (hidden), ``diff-schedule``,
``coalesce-search``, and ``select-order-search``. They are defined here as
plain (undecorated) functions; __init__.py re-applies the
``@debug_app.command(...)`` decorators at the original registration positions
so the command surface and ordering stay byte-identical.

Shared helpers (and the module-level names the tests patch on the
``src.cli.debug`` package) still live in cli/debug/__init__.py. They are
reached via call-time (deferred) ``from src.cli.debug import ...`` imports
inside the function bodies -- a load-time import would create a cycle
(__init__ imports this module) and would also break
``monkeypatch.setattr(debug_cli, ...)`` semantics, since the patched name must
resolve against __init__ at call time.
"""
from __future__ import annotations

import itertools
import json
import tempfile
import time
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Mapping,
    Optional,
)

import typer

__all__ = [
    "suggest_schedule_source_compat",
    "debug_diff_schedule",
    "debug_coalesce_search_cmd",
    "debug_select_order_search_cmd",
]


def suggest_schedule_source_compat(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list that produced the forced pcdump, "
                "e.g. 'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Path | None,
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Path | None,
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Backward-compatible alias for `debug suggest schedule`."""

    from src.cli.debug import (
        _emit_suggest_schedule_source,
    )
    _emit_suggest_schedule_source(
        function=function,
        force_schedule=force_schedule,
        against=against,
        pcdump=pcdump,
        source_file=source_file,
        json_out=json_out,
    )



def debug_diff_schedule(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list to compare, e.g. "
                "'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Diff real vs forced scheduler-window decisions."""

    from src.cli.debug import (
        DEFAULT_MELEE_ROOT,
        _find_unit_for_function,
        _resolve_pcdump_path,
        _validate_force_schedule,
    )
    from ...mwcc_debug.schedule_explain import (
        diff_schedule,
        render_diff_json,
        render_diff_text,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    if not against.is_file():
        raise typer.BadParameter(f"forced-path pcdump not found: {against}")
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)
    report = diff_schedule(
        pcdump_path.read_text(),
        against.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
    )
    print(render_diff_json(report) if json_out else render_diff_text(report))



def debug_coalesce_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    target: Annotated[
        Optional[str],
        typer.Option(
            "--target",
            help=(
                "Target virtual pair(s), e.g. r37=r40 or r37=r40,r43=r33. "
                "May be omitted when --trace-copy-json is supplied."
            ),
        ),
    ] = None,
    trace_copy_json: Annotated[
        Optional[Path],
        typer.Option(
            "--trace-copy-json",
            help=(
                "trace-copy --json report to derive a copy-survived repair "
                "target and register class."
            ),
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved baseline pcdump whose source is newer "
                "than the cache. Off by default so source scores cannot be "
                "mixed with stale allocator facts."
            ),
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate coalesce-directed probes.",
        ),
    ] = None,
    split_var: Annotated[
        Optional[str],
        typer.Option(
            "--split-var",
            help=(
                "Generate anti-coalesce volatile-copy probes for this local "
                "variable before falling back to generic lifetime/layout probes."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help=(
                "Compile generated source probes. Enabled by default so the "
                "plain command emits ranked, scored candidates."
            ),
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker; "
                "use --no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to compile or list.",
        ),
    ] = 8,
    include_transform_corpus: Annotated[
        bool,
        typer.Option(
            "--include-transform-corpus/--no-include-transform-corpus",
            help=(
                "Opt in to transform-corpus source-shape probes after the "
                "coalesce and lifetime/layout probe families."
            ),
        ),
    ] = False,
    transform_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--transform-family",
            help=(
                "Transform-corpus source-shape family to generate. Repeat or "
                "pass comma-separated names; passing this also opts in."
            ),
        ),
    ] = None,
    transform_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--transform-force-phys",
            "--directed-force-phys",
            help=(
                "Proof mapping for transform-corpus source-shape probes, "
                "e.g. IG:PHYS or comma-separated IG:PHYS entries."
            ),
        ),
    ] = None,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Search source-shape probes by target coalescing/interference objective."""

    from src.cli.debug import (
        DEFAULT_MELEE_ROOT,
        _append_transform_corpus_probes,
        _coalesce_force_phys_objective_fields,
        _coalesce_generated_local_from_variant,
        _coalesce_parse_force_phys_map,
        _coalesce_search_probe_root,
        _copy_propagation_repair_summary,
        _copy_propagation_repair_text,
        _copy_survived_continuation_handoff,
        _copy_survived_repair_summary,
        _copy_survived_variant_hit,
        _find_unit_for_function,
        _full_unit_source_for_probe,
        _generate_anti_coalesce_split_probes,
        _generate_copy_survived_pointer_reset_probes,
        _load_trace_copy_repair_target,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _parse_virtual_pair_csv,
        _pressure_class_id,
        _pressure_signature_from_pcdump_or_exit,
        _probe_requires_full_unit_source,
        _register_class_from_pair_csv,
        _resolve_existing_cli_file,
        _resolve_pcdump_path,
        _retain_coalesce_search_pcdump,
        _retain_coalesce_search_source,
        _same_filesystem_path,
        _select_order_source_match_percent,
        _trace_copy_json_summary,
    )
    from ...mwcc_debug.coalesce_search import (
        rank_coalesce_candidates,
        render_coalesce_variant,
        score_coalesce_delta,
    )
    from ...mwcc_debug.call_return_shape import (
        CALL_RETURN_USE_SHAPE_OPERATOR,
        generate_call_return_use_shape_probes,
    )
    from ...mwcc_debug.diff_capture import (
        CompileFailure,
        DiffInput,
        compile_source_variant,
    )
    from ...mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        pressure_signature_from_pcdump,
    )

    trace_copy_target = (
        None if trace_copy_json is None else _load_trace_copy_repair_target(
            trace_copy_json,
            function=function,
        )
    )
    if target is not None and target.strip():
        target_pairs = _parse_virtual_pair_csv(target)
        target_source = "--target"
        if trace_copy_target is not None:
            trace_pair = (
                trace_copy_target["from_virtual"],
                trace_copy_target["to_virtual"],
            )
            if trace_pair not in target_pairs:
                typer.echo(
                    "--target does not include the trace-copy virtual pair "
                    f"{trace_pair[0]}={trace_pair[1]}.",
                    err=True,
                )
                raise typer.Exit(2)
    elif trace_copy_target is not None:
        target_pairs = [(
            trace_copy_target["from_virtual"],
            trace_copy_target["to_virtual"],
        )]
        target_source = "trace-copy-json"
    else:
        target_pairs = []
        target_source = None
    if not target_pairs:
        typer.echo("--target or --trace-copy-json is required.", err=True)
        raise typer.Exit(2)
    register_class = None
    if trace_copy_target is not None:
        register_class = trace_copy_target.get("register_class")
    if register_class is None:
        register_class = _register_class_from_pair_csv(target)
    register_class = register_class or "gpr"
    class_id = _pressure_class_id(register_class)

    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=not allow_stale_pcdump,
    )
    baseline_text = baseline_path.read_text()
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=target_pairs,
        class_id=class_id,
        spill_class_id=class_id,
    )

    def _live_source_for_function() -> Path | None:
        unit_for_path = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit_for_path is None:
            return None
        candidate_source = DEFAULT_MELEE_ROOT / "src" / f"{unit_for_path}.c"
        if candidate_source.exists():
            return candidate_source
        return None

    def _same_tu_unit_source_for_probe_source(path: Path) -> Path | None:
        try:
            path.resolve().relative_to((DEFAULT_MELEE_ROOT / "src").resolve())
        except ValueError:
            return _live_source_for_function()
        return path

    source_text = None
    source_label = None
    source_path_for_probes: Path | None = None
    unit = None
    if source_file is not None:
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        source_text = source_file.read_text()
        source_label = str(source_file)
        source_path_for_probes = _same_tu_unit_source_for_probe_source(
            source_file,
        )
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()
                source_path_for_probes = src_path
                try:
                    source_label = str(src_path.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(src_path)
    if source_path_for_probes is None:
        unit_for_path = unit or _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit_for_path is not None:
            candidate_source = DEFAULT_MELEE_ROOT / "src" / f"{unit_for_path}.c"
            if candidate_source.exists():
                source_path_for_probes = candidate_source

    def _source_file_requires_retained_full_unit(path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(DEFAULT_MELEE_ROOT.resolve())
        except ValueError:
            return True
        return not relative.parts or relative.parts[0] != "src"

    def _source_file_is_repo_retained_source(path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(DEFAULT_MELEE_ROOT.resolve())
        except ValueError:
            return False
        return (
            len(relative.parts) >= 2
            and relative.parts[0] == "build"
            and relative.parts[1] in {"diagnostics", "mwcc_debug_cache"}
        )

    source_file_requires_retained_full_unit = (
        source_file is not None
        and _source_file_requires_retained_full_unit(source_file)
    )

    retained_full_unit_source = (
        source_file_requires_retained_full_unit
        and source_path_for_probes is not None
    )

    probes = []
    force_phys_targets = _coalesce_parse_force_phys_map(transform_force_phys)
    if source_text:
        probes.extend(generate_call_return_use_shape_probes(
            source_text,
            function,
            trace_copy_target,
            max_probes=max_probes,
        ))
        probes.extend(_generate_copy_survived_pointer_reset_probes(
            source_text,
            function,
            trace_copy_target,
            max_probes=max(0, max_probes - len(probes)),
        ))
        if split_var:
            probes.extend(_generate_anti_coalesce_split_probes(
                source_text,
                function,
                split_var,
                max_probes=max(0, max_probes - len(probes)),
            ))
        remaining_probe_budget = max(0, max_probes - len(probes))
        if remaining_probe_budget:
            probes.extend(generate_lifetime_layout_probes(
                source_text,
                function,
                frame_reservation_bytes=frame_reservation_bytes,
                max_probes=remaining_probe_budget,
            ))
    if source_file is not None and (include_transform_corpus or transform_family):
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    _append_transform_corpus_probes(
        probes,
        source_text=source_text,
        function=function,
        unit=unit,
        include=include_transform_corpus,
        families=transform_family,
        force_phys=transform_force_phys,
        max_probes=max_probes,
    )
    variants: list[dict] = []
    generated_source_dir: Path | None = None

    def _generated_source_path(path: Path) -> bool:
        if generated_source_dir is None:
            return False
        try:
            path.resolve().relative_to(generated_source_dir.resolve())
        except ValueError:
            return False
        return True

    def _compile_failure_output_path(exc: CompileFailure) -> Path | None:
        command = getattr(exc, "command", None)
        if not isinstance(command, list):
            return None
        for index, token in enumerate(command[:-1]):
            if token == "--output":
                return Path(command[index + 1])
        return None

    def _attach_compile_failure_metadata(
        failed: dict[str, Any],
        exc: CompileFailure,
        *,
        label: str,
        probe_root: Path,
        retention_reason: str,
    ) -> None:
        attempted_path = _compile_failure_output_path(exc)
        if attempted_path is not None:
            failed["pcdump_attempted_path"] = str(attempted_path)
        failed["compile_returncode"] = exc.returncode
        failed["compile_command"] = list(exc.command)
        failed["compile_stdout"] = exc.stdout
        failed["compile_stderr"] = exc.stderr
        if attempted_path is None:
            failed["pcdump_missing"] = True
            return
        try:
            pcdump_text = attempted_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            failed["pcdump_missing"] = True
            return
        try:
            retained_pcdump = _retain_coalesce_search_pcdump(
                pcdump_text,
                candidate_id=label,
                probe_root=probe_root,
                reason=retention_reason,
            )
        except OSError as retain_exc:
            failed["pcdump_retention_error"] = str(retain_exc)
            failed["pcdump_missing"] = True
            return
        failed["pcdump_path"] = str(retained_pcdump)
        failed["pcdump_retention_reason"] = retention_reason
        if not pcdump_text:
            failed["pcdump_empty"] = True

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
        unit_source: Path | None = None,
        full_unit_source: bool = False,
        probe_payload: Mapping[str, Any] | None = None,
        generated_probe: bool = False,
        original_path: Path | None = None,
    ) -> None:
        try:
            if full_unit_source and unit_source is None:
                raise ValueError(
                    "full-unit transform probe requires a resolved unit source"
                )
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                compile_kwargs = dict(
                    diff_input=DiffInput(
                        label=label,
                        token=str(path),
                        kind="source",
                        path=path,
                    ),
                    function=function,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=timeout,
                )
                if unit_source is not None:
                    compile_kwargs["unit_source"] = unit_source
                candidate_text = compile_source_variant(**compile_kwargs)
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")
            match_percent = None
            match_percent_error = None
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("coalesce-search", label)
                    if not json_out
                    else None
                )
                match_kwargs = dict(
                    path=path,
                    function=function,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=timeout,
                    status=status,
                )
                if full_unit_source:
                    match_kwargs["full_unit_source"] = True
                match_percent, match_percent_error = (
                    _select_order_source_match_percent(**match_kwargs)
                )
            candidate_sig = pressure_signature_from_pcdump(
                candidate_text,
                function,
                pairs=target_pairs,
                class_id=class_id,
                spill_class_id=class_id,
            )
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = score_coalesce_delta(
                delta,
                target_pairs=target_pairs,
                match_percent=match_percent,
            )
            objective_dict = objective.to_dict()
            if force_phys_targets:
                force_fields = _coalesce_force_phys_objective_fields(
                    baseline_text=baseline_text,
                    candidate_text=candidate_text,
                    function=function,
                    class_id=class_id,
                    force_phys=force_phys_targets,
                )
                if force_fields:
                    sort_key = list(objective_dict.get("sort_key") or [])
                    objective_dict.update(force_fields)
                    objective_dict["sort_key"] = [
                        float(bool(force_fields.get("force_phys_satisfied"))),
                        float(force_fields.get("force_phys_satisfied_count") or 0),
                        -float(force_fields.get("force_phys_distance") or 0),
                        *sort_key,
                    ]
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective_dict,
                "register_class": register_class,
            }
            if probe_payload is not None:
                variant["probe"] = dict(probe_payload)
                description = probe_payload.get("description")
                if description is not None:
                    variant["description"] = description
                provenance = probe_payload.get("provenance")
                if isinstance(provenance, Mapping):
                    variant["provenance"] = dict(provenance)
                    source_hunk = provenance.get("source_hunk")
                    if isinstance(source_hunk, Mapping):
                        variant["source_hunk"] = dict(source_hunk)
            if generated_probe:
                variant["generated_probe"] = True
            if match_percent_error is not None:
                variant["match_percent_error"] = match_percent_error
            if source_retained is None and path.suffix == ".c":
                source_retained = path
            if source_retained is not None:
                variant["source_retained"] = str(source_retained)
            variant_hit = _copy_survived_variant_hit(variant)
            retain_generated_source_shape = (
                generated_probe
                and operator == CALL_RETURN_USE_SHAPE_OPERATOR
            )
            if (
                path.suffix == ".c"
                and trace_copy_target is not None
                and (variant_hit or retain_generated_source_shape)
            ):
                retention_reason = (
                    "source_actionable" if variant_hit else "source_shape_scored"
                )
                variant["source_retention_reason"] = retention_reason
                probe_root = _coalesce_search_probe_root(
                    DEFAULT_MELEE_ROOT,
                    function,
                )
                if generated_probe:
                    try:
                        retained_path = _retain_coalesce_search_source(
                            path,
                            candidate_id=label,
                            probe_root=probe_root,
                            reason=retention_reason,
                        )
                        if not _same_filesystem_path(path, retained_path):
                            variant["original_path"] = str(path)
                        variant["path"] = str(retained_path)
                        source_retained = retained_path
                    except OSError as retain_exc:
                        variant["source_retention_error"] = str(retain_exc)
                if source_retained is not None:
                    variant["source_retained"] = str(source_retained)
                    variant["objective"] = dict(variant["objective"])
                    variant["objective"]["source_path"] = str(source_retained)
                try:
                    retained_pcdump = _retain_coalesce_search_pcdump(
                        candidate_text,
                        candidate_id=label,
                        probe_root=probe_root,
                        reason=retention_reason,
                    )
                    variant["pcdump_path"] = str(retained_pcdump)
                    variant["objective"] = dict(variant["objective"])
                    variant["objective"]["pcdump_path"] = str(retained_pcdump)
                except OSError as retain_exc:
                    variant["pcdump_retention_error"] = str(retain_exc)
                if variant_hit:
                    generated_local = _coalesce_generated_local_from_variant(variant)
                    if generated_local is not None:
                        variant["generated_local"] = generated_local
                    continuation_unit = unit or _find_unit_for_function(
                        function,
                        DEFAULT_MELEE_ROOT,
                    )
                    continuation = _copy_survived_continuation_handoff(
                        function=function,
                        unit=continuation_unit,
                        trace_target=trace_copy_target,
                        variant=variant,
                        transform_force_phys=transform_force_phys,
                        melee_root=DEFAULT_MELEE_ROOT,
                    )
                    if continuation is not None:
                        variant["continuation"] = continuation
            elif (
                path.suffix == ".c"
                and full_unit_source
                and source_retained is not None
            ):
                try:
                    probe_root = _coalesce_search_probe_root(
                        DEFAULT_MELEE_ROOT,
                        function,
                    )
                    retained_pcdump = _retain_coalesce_search_pcdump(
                        candidate_text,
                        candidate_id=label,
                        probe_root=probe_root,
                        reason="retained_full_unit_probe",
                    )
                    variant["pcdump_path"] = str(retained_pcdump)
                    variant["objective"] = dict(variant["objective"])
                    variant["objective"]["pcdump_path"] = str(retained_pcdump)
                except OSError as retain_exc:
                    variant["pcdump_retention_error"] = str(retain_exc)
            variants.append(variant)
        except Exception as exc:
            error_text = str(exc)
            failed = {
                "label": label,
                "operator": operator,
                "status": "failed",
                "path": str(path),
                "error": error_text,
            }
            function_missing = "not found in pcdump" in error_text
            retain_generated_failure = (
                path.suffix == ".c"
                and generated_probe
                and (
                    isinstance(exc, CompileFailure)
                    or function_missing
                    or full_unit_source
                    or _generated_source_path(path)
                )
            )
            source_shape_failure = (
                path.suffix == ".c"
                and trace_copy_target is not None
                and generated_probe
                and operator == CALL_RETURN_USE_SHAPE_OPERATOR
            )
            if retain_generated_failure or source_shape_failure:
                retention_reason = (
                    "terminal_target_missing"
                    if function_missing
                    else "source_shape_failed"
                    if source_shape_failure
                    else "compile_failed"
                )
                try:
                    probe_root = _coalesce_search_probe_root(
                        DEFAULT_MELEE_ROOT,
                        function,
                    )
                    retained_path = _retain_coalesce_search_source(
                        path,
                        candidate_id=label,
                        probe_root=probe_root,
                        reason=retention_reason,
                    )
                    original_source = original_path or path
                    if not _same_filesystem_path(original_source, retained_path):
                        failed["original_path"] = str(original_source)
                    failed["path"] = str(retained_path)
                    failed["source_retained"] = str(retained_path)
                    failed["source_retention_reason"] = retention_reason
                    if isinstance(exc, CompileFailure):
                        _attach_compile_failure_metadata(
                            failed,
                            exc,
                            label=label,
                            probe_root=probe_root,
                            retention_reason=retention_reason,
                        )
                except OSError as retain_exc:
                    failed["source_retention_error"] = str(retain_exc)
            elif isinstance(exc, CompileFailure):
                try:
                    probe_root = _coalesce_search_probe_root(
                        DEFAULT_MELEE_ROOT,
                        function,
                    )
                    _attach_compile_failure_metadata(
                        failed,
                        exc,
                        label=label,
                        probe_root=probe_root,
                        retention_reason=(
                            "terminal_target_missing"
                            if function_missing
                            else "compile_failed"
                        ),
                    )
                except OSError as retain_exc:
                    failed["pcdump_retention_error"] = str(retain_exc)
            if probe_payload is not None:
                failed["probe"] = dict(probe_payload)
                description = probe_payload.get("description")
                if description is not None:
                    failed["description"] = description
                provenance = probe_payload.get("provenance")
                if isinstance(provenance, Mapping):
                    failed["provenance"] = dict(provenance)
            if generated_probe:
                failed["generated_probe"] = True
            if "source_retained" not in failed:
                if source_retained is not None:
                    failed["source_retained"] = str(source_retained)
                elif path.suffix == ".c" and path.exists():
                    failed["source_retained"] = str(path)
            variants.append(failed)

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if not probes and not candidates:
            typer.echo(
                "source unavailable or no probes generated; pass --source-file "
                "or --candidate OPERATOR=path.",
                err=True,
            )
            raise typer.Exit(2)
        if probes:
            if (
                source_file is not None
                and source_path_for_probes is None
                and _source_file_is_repo_retained_source(source_file)
            ):
                typer.echo(
                    "unable to resolve live src/... compile unit for retained "
                    f"source file {source_file} while probing {function}.",
                    err=True,
                )
                raise typer.Exit(2)
            generated_source_dir = Path(tempfile.mkdtemp(prefix="melee_coalesce_search_"))
            for probe in probes:
                path = generated_source_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                original_path = path
                full_unit_source = (
                    retained_full_unit_source
                    or _probe_requires_full_unit_source(probe)
                )
                source_retained = path
                unit_source_for_probe = _full_unit_source_for_probe(
                    probe,
                    source_path_for_probes,
                )
                if retained_full_unit_source:
                    probe_root = _coalesce_search_probe_root(
                        DEFAULT_MELEE_ROOT,
                        function,
                    )
                    retained_path = _retain_coalesce_search_source(
                        path,
                        candidate_id=probe.label,
                        probe_root=probe_root,
                        reason="retained_full_unit_probe",
                    )
                    path = retained_path
                    source_retained = retained_path
                    unit_source_for_probe = source_path_for_probes
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                    source_retained=source_retained,
                    unit_source=unit_source_for_probe,
                    full_unit_source=full_unit_source,
                    probe_payload=probe.to_dict(),
                    generated_probe=True,
                    original_path=original_path,
                )

    ranked_variants = rank_coalesce_candidates(variants)
    terminal_summary = _coalesce_all_failed_terminal_summary(
        variants=ranked_variants,
        source_label=source_label,
        generated_source_dir=generated_source_dir,
    )
    copy_propagation_repair = (
        None if trace_copy_target is None else _copy_propagation_repair_summary(
            trace_copy_target,
            ranked_variants,
        )
    )
    if json_out:
        payload = {
            "function": function,
            "target_source": target_source,
            "target_pairs": [list(pair) for pair in target_pairs],
            "register_class": register_class,
            "ranking": (
                "target coalesce objective, final match percent tiebreaker"
            ),
            "baseline": baseline.to_dict(),
            "source": source_label,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "probes": [probe.to_dict() for probe in probes],
            "variants": ranked_variants,
        }
        if terminal_summary is not None:
            payload["status"] = "terminal-blocked"
            payload["terminal_blocker"] = terminal_summary["terminal_blocker"]
            payload["terminal_summary"] = terminal_summary
        if trace_copy_target is not None:
            payload["trace_copy"] = _trace_copy_json_summary(trace_copy_target)
            payload["copy_survived_repair"] = _copy_survived_repair_summary(
                trace_copy_target,
                ranked_variants,
                function=function,
                unit=unit or _find_unit_for_function(function, DEFAULT_MELEE_ROOT),
                transform_force_phys=transform_force_phys,
                melee_root=DEFAULT_MELEE_ROOT,
            )
            payload["copy_propagation_repair"] = copy_propagation_repair
        print(json.dumps(payload, indent=2))
        return

    print(f"coalesce-search - {function}")
    if trace_copy_target is not None:
        print(
            "trace-copy: "
            f"{trace_copy_target.get('trace_status') or '?'} "
            f"({trace_copy_target.get('likely_cause') or 'unknown cause'})"
        )
    reg_prefix = "f" if register_class == "fpr" else "r"
    print(
        "target: "
        + ", ".join(
            f"{reg_prefix}{left}/{reg_prefix}{right}"
            for left, right in target_pairs
        )
    )
    if copy_propagation_repair is not None:
        repair_line = _copy_propagation_repair_text(copy_propagation_repair)
        if repair_line is not None:
            print(repair_line)
    print("ranking: target coalesce objective, final match percent tiebreaker")
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            print(render_coalesce_variant(variant))
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")


def _coalesce_all_failed_terminal_summary(
    *,
    variants: list[dict],
    source_label: str | None,
    generated_source_dir: Path | None,
) -> dict[str, Any] | None:
    if not variants or any(variant.get("status") == "ok" for variant in variants):
        return None
    errors = [
        str(variant.get("error") or "")
        for variant in variants
        if isinstance(variant, Mapping)
    ]
    if not errors:
        return None
    function_missing = all("not found in pcdump" in error for error in errors)
    terminal_blocker = (
        "retained-target-function-missing-from-pcdump"
        if function_missing
        else "coalesce-search-all-variants-failed"
    )
    source_retained = [
        value
        for variant in variants
        if isinstance(variant, Mapping)
        and isinstance((value := variant.get("source_retained")), str)
    ]
    pcdumps = [
        value
        for variant in variants
        if isinstance(variant, Mapping)
        and isinstance((value := variant.get("pcdump_path")), str)
    ]
    pcdump_attempted = [
        value
        for variant in variants
        if isinstance(variant, Mapping)
        and isinstance((value := variant.get("pcdump_attempted_path")), str)
        and not isinstance(variant.get("pcdump_path"), str)
    ]
    compile_failures = []
    for variant in variants:
        if not isinstance(variant, Mapping):
            continue
        if isinstance(variant.get("pcdump_path"), str):
            continue
        if not any(
            key in variant
            for key in (
                "compile_returncode",
                "compile_command",
                "compile_stdout",
                "compile_stderr",
            )
        ):
            continue
        compile_failures.append({
            "label": variant.get("label"),
            "returncode": variant.get("compile_returncode"),
            "command": variant.get("compile_command"),
            "stdout": variant.get("compile_stdout"),
            "stderr": variant.get("compile_stderr"),
        })
    summary = {
        "kind": "coalesce-search-terminal-summary",
        "status": "terminal-blocked",
        "terminal_blocker": terminal_blocker,
        "variant_count": len(variants),
        "failed_variant_count": sum(
            1 for variant in variants if variant.get("status") != "ok"
        ),
        "source": source_label,
        "generated_source_dir": (
            str(generated_source_dir) if generated_source_dir is not None else None
        ),
        "source_retained": source_retained[:8],
        "pcdump_path": pcdumps[:8],
        "sample_errors": errors[:3],
        "reason": (
            "all generated coalesce probes failed before scoring"
            if not function_missing
            else "all generated coalesce probes compiled without the requested target function"
        ),
    }
    if pcdump_attempted:
        summary["pcdump_attempted_path"] = pcdump_attempted[:8]
    pcdump_missing_count = sum(
        1
        for variant in variants
        if isinstance(variant, Mapping) and variant.get("pcdump_missing") is True
    )
    pcdump_empty_count = sum(
        1
        for variant in variants
        if isinstance(variant, Mapping) and variant.get("pcdump_empty") is True
    )
    if pcdump_missing_count:
        summary["pcdump_missing_count"] = pcdump_missing_count
    if pcdump_empty_count:
        summary["pcdump_empty_count"] = pcdump_empty_count
    if compile_failures:
        summary["compile_failures"] = compile_failures[:3]
    return summary



def debug_select_order_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Target select order(s), e.g. r32<r33 or r43<r33,r40<r33.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved baseline pcdump whose source is newer "
                "than the cache. Off by default so source scores cannot be "
                "mixed with stale allocator facts."
            ),
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate select-order-directed probes.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    probe_provenance: Annotated[
        Optional[list[str]],
        typer.Option(
            "--probe-provenance",
            help=(
                "JSON object describing the matching --candidate provenance. "
                "Repeat in candidate order."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class id from COLORGRAPH DECISIONS.",
        ),
    ] = 0,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help=(
                "Compile generated source probes. Enabled by default so the "
                "plain command emits ranked, scored candidates."
            ),
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker; "
                "use --no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to compile or list.",
        ),
    ] = 8,
    include_transform_corpus: Annotated[
        bool,
        typer.Option(
            "--include-transform-corpus/--no-include-transform-corpus",
            help=(
                "Opt in to transform-corpus source-shape probes for the "
                "single-probe select-order search list."
            ),
        ),
    ] = False,
    transform_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--transform-family",
            help=(
                "Transform-corpus source-shape family to generate. Repeat or "
                "pass comma-separated names; passing this also opts in."
            ),
        ),
    ] = None,
    transform_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--transform-force-phys",
            "--directed-force-phys",
            help=(
                "Proof mapping for transform-corpus source-shape probes, "
                "e.g. IG:PHYS or comma-separated IG:PHYS entries."
            ),
        ),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Proof mapping for residual first-divergence scoring, e.g. "
                "IG:PHYS or comma-separated IG:PHYS entries. Alias of "
                "--transform-force-phys for select-order proof workflows."
            ),
        ),
    ] = None,
    residual_first_divergence_top: Annotated[
        Optional[int],
        typer.Option(
            "--residual-first-divergence-top",
            help=(
                "Attach first-divergence residual analysis to the top N ranked "
                "successful candidates. Omit for automatic top-3 on force-phys "
                "misses; pass 0 to disable."
            ),
        ),
    ] = None,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    beam_depth: Annotated[
        int,
        typer.Option(
            "--beam-depth",
            help=(
                "Compose generated source probes for N rounds. 0 keeps the "
                "single-probe search."
            ),
        ),
    ] = 0,
    beam_width: Annotated[
        int,
        typer.Option(
            "--beam-width",
            help="Number of real-score-ranked candidates to expand per beam round.",
        ),
    ] = 4,
    guard_repair_depth: Annotated[
        Optional[int],
        typer.Option(
            "--guard-repair-depth",
            help=(
                "Repair rounds seeded from structural-guard-rejected "
                "force-phys hits. Omitted auto-enables depth 1 for "
                "force-phys beam mode."
            ),
        ),
    ] = None,
    guard_repair_seeds: Annotated[
        Optional[list[str]],
        typer.Option(
            "--guard-repair-seed",
            help=(
                "Retained .c source to score and use as a protected guard-repair "
                "frontier. Format OPERATOR=path or LABEL:OPERATOR=path. "
                "Requires --force-phys or --transform-force-phys."
            ),
        ),
    ] = None,
    guard_repair_width: Annotated[
        int,
        typer.Option(
            "--guard-repair-width",
            help="Number of guard-repair seeds/frontier candidates to expand.",
        ),
    ] = 2,
    campaign_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--campaign-dir",
            help=(
                "Directory for composed probe sources and ledger. Defaults to "
                "a temporary melee_select_order_beam_* directory."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help=(
                "Top-level search timeout in seconds; compile and source-score "
                "steps share the remaining campaign budget."
            ),
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Search source-shape probes by target COLORGRAPH select-order objective."""

    from src.cli.debug import (
        DEFAULT_MELEE_ROOT,
        _FPR_SELECT_ORDER_TRANSFORM_FAMILIES,
        _GPR_SELECT_ORDER_TRANSFORM_FAMILIES,
        _MalformedSourceCandidate,
        _SelectOrderCommandSourceRestore,
        _SourceRestoreBytesError,
        _append_transform_corpus_probes,
        _auto_pcdump_cache_metadata,
        _compact_source_hunk_for_function,
        _find_unit_for_function,
        _format_select_order_residual,
        _full_unit_source_for_probe,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _parse_probe_provenance,
        _parse_select_order_guard_repair_seed,
        _parse_virtual_order_csv,
        _path_inside_repo,
        _pressure_signature_from_pcdump_or_exit,
        _prevalidate_lifetime_layout_source_candidate,
        _probe_requires_full_unit_source,
        _rank_select_order_candidates_real_first,
        _register_tiebreak_window_order_fallback,
        _resolve_pcdump_path,
        _select_order_augmented_window_order_leads,
        _select_order_candidate_residual_first_divergence,
        _select_order_close_source_restore,
        _select_order_complement_target_summary,
        _select_order_default_complement_targets,
        _select_order_diagnostic_buckets,
        _select_order_force_phys_hit_registers,
        _select_order_guard_repair_candidate_summary,
        _select_order_guard_repair_entry_protected_complement,
        _select_order_guard_repair_reconciliation_frontier_entry,
        _select_order_guard_repair_seed_variants,
        _select_order_guard_repair_summary,
        _select_order_guard_repair_variant_sort_key,
        _select_order_json_safe,
        _select_order_materializable_targeted_interference_delta,
        _select_order_protected_register_preservation,
        _select_order_public_variants,
        _select_order_refresh_window_order_probe_diagnostics,
        _select_order_residual_variant_labels_from_buckets,
        _select_order_safe_label,
        _select_order_source_attributed_fallback_lead_count,
        _select_order_source_attributions_for_leads,
        _select_order_source_bridge_summary,
        _select_order_source_fingerprints,
        _select_order_source_hunk_crossover_probes,
        _select_order_source_score,
        _select_order_subtractive_source_hunk_repair_probes,
        _select_order_tag_targeted_interference_probe,
        _select_order_terminal_exhaustion_summary,
        _select_order_variant_target_score,
        _select_order_window_order_probe_reserve,
        _solve_source_attribution_dict,
        _source_restore_byte_guards,
        _timeout_before_deadline,
        _write_select_order_timeout_ledger,
    )
    from ...mwcc_debug.diff_capture import (
        CompileFailure,
        DiffInput,
        compile_source_variant,
    )
    from ...mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        pressure_signature_from_pcdump,
    )
    from ...mwcc_debug.select_order_search import (
        rank_select_order_candidates,
        render_select_order_variant,
        score_select_order_candidate,
    )
    from ...search.directed.transform_probe_adapter import (
        TransformProbeConfigError,
        parse_transform_force_phys,
    )

    target_orders = _parse_virtual_order_csv(target)
    if not target_orders:
        typer.echo("--target is required.", err=True)
        raise typer.Exit(2)
    if (
        residual_first_divergence_top is not None
        and residual_first_divergence_top < 0
    ):
        raise typer.BadParameter("--residual-first-divergence-top must be >= 0")
    try:
        force_phys_map = parse_transform_force_phys(force_phys)
        transform_force_map = parse_transform_force_phys(transform_force_phys)
    except TransformProbeConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if (
        force_phys is not None
        and transform_force_phys is not None
        and force_phys_map != transform_force_map
    ):
        raise typer.BadParameter(
            "--force-phys and --transform-force-phys specify different maps"
        )
    proof_force_map = (
        force_phys_map if force_phys is not None else transform_force_map
    )
    effective_force_phys = force_phys if force_phys is not None else transform_force_phys
    explicit_guard_repair_seed_specs = [
        _parse_select_order_guard_repair_seed(spec)
        for spec in guard_repair_seeds or []
    ]
    explicit_guard_repair_seed_labels: set[str] = set()
    for seed_spec in explicit_guard_repair_seed_specs:
        label = seed_spec["label"]
        if label in explicit_guard_repair_seed_labels:
            raise typer.BadParameter(
                f"duplicate guard repair seed label: {label}"
            )
        explicit_guard_repair_seed_labels.add(label)
    if explicit_guard_repair_seed_specs and not proof_force_map:
        raise typer.BadParameter(
            "--guard-repair-seed requires --force-phys or --transform-force-phys"
        )
    if guard_repair_depth is not None and guard_repair_depth < 0:
        raise typer.BadParameter("--guard-repair-depth must be >= 0")
    if guard_repair_width <= 0:
        raise typer.BadParameter("--guard-repair-width must be positive")
    effective_guard_repair_depth = (
        guard_repair_depth
        if guard_repair_depth is not None
        else (
            1
            if proof_force_map
            and (beam_depth > 0 or bool(explicit_guard_repair_seed_specs))
            else 0
        )
    )
    command_deadline = (
        time.monotonic() + timeout
        if timeout is not None and timeout > 0
        else None
    )
    timed_out = False
    timeout_error: str | None = None

    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=not allow_stale_pcdump,
    )
    baseline_pcdump_source = "explicit" if pcdump is not None else "auto-cache"
    baseline_cache = _auto_pcdump_cache_metadata(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
    )
    baseline_text = baseline_path.read_text(encoding="utf-8", errors="replace")
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=target_orders,
        class_id=class_id,
    )

    source_text = None
    source_label = None
    source_path_for_probes: Path | None = None
    unit = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
        if _path_inside_repo(source_file, DEFAULT_MELEE_ROOT):
            source_path_for_probes = source_file
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()
                source_path_for_probes = src_path
                try:
                    source_label = str(src_path.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(src_path)
    if source_path_for_probes is None:
        unit_for_path = unit or _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit_for_path is not None:
            candidate_source = DEFAULT_MELEE_ROOT / "src" / f"{unit_for_path}.c"
            if candidate_source.exists():
                source_path_for_probes = candidate_source
    live_unit_source_for_restore: Path | None = None
    try:
        unit_for_restore = unit or _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    except Exception:
        unit_for_restore = None
    if unit_for_restore is not None:
        candidate_source = DEFAULT_MELEE_ROOT / "src" / f"{unit_for_restore}.c"
        if candidate_source.exists():
            live_unit_source_for_restore = candidate_source
    command_source_restore = _SelectOrderCommandSourceRestore(
        source_path_for_probes,
        melee_root=DEFAULT_MELEE_ROOT,
    )

    auto_transform_families: tuple[str, ...] = ()
    if class_id == 1 and effective_force_phys and not transform_family:
        auto_transform_families = _FPR_SELECT_ORDER_TRANSFORM_FAMILIES
    elif class_id == 0 and effective_force_phys and not transform_family:
        auto_transform_families = _GPR_SELECT_ORDER_TRANSFORM_FAMILIES

    if (
        source_file is not None
        and (include_transform_corpus or transform_family)
    ):
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)

    window_order_fallback: dict | None = None
    window_order_source_attributions: dict[int, Any] = {}
    window_order_probe_lead_diagnostics: list[dict[str, Any]] = []
    window_order_probe_planner_runs: list[dict[str, Any]] = []
    if effective_force_phys:
        window_order_fallback = _register_tiebreak_window_order_fallback(
            function=function,
            class_id=class_id,
            pcdump_path=baseline_path,
            pcdump_text=baseline_text,
            allow_auto_pcdump=False,
            pcdump_source=baseline_pcdump_source,
            force_phys=proof_force_map,
        )
        window_order_source_attributions = _select_order_source_attributions_for_leads(
            pcdump_text=baseline_text,
            function=function,
            class_id=class_id,
            source_text=source_text,
            source_file=(
                str(source_path_for_probes)
                if source_path_for_probes is not None else source_label
            ),
            fallback=window_order_fallback,
            extra_virtuals=proof_force_map.keys() if proof_force_map else (),
        )
        if isinstance(window_order_fallback, Mapping) and proof_force_map:
            original_leads = window_order_fallback.get("leads")
            augmented_leads = _select_order_augmented_window_order_leads(
                original_leads,
                force_phys=proof_force_map,
                class_id=class_id,
                source_attributions=window_order_source_attributions,
                priority_targets=itertools.chain.from_iterable(target_orders),
            )
            original_lead_list = (
                original_leads if isinstance(original_leads, list) else []
            )
            if augmented_leads != original_lead_list:
                promoted = [
                    lead for lead in augmented_leads
                    if lead.get("source") == "force-phys-attributed-temp"
                ]
                window_order_fallback = {
                    **dict(window_order_fallback),
                    "leads": augmented_leads,
                    "force_phys_attributed_temp_leads": promoted,
                }

    def _window_order_source_probes_for(
        current_source: str,
        *,
        max_count: int,
    ) -> list[Any]:
        nonlocal window_order_probe_lead_diagnostics
        if (
            not isinstance(window_order_fallback, Mapping)
            or not window_order_fallback.get("leads")
        ):
            return []
        from ...search.directed import window_order_source as window_order_source_mod

        planned = window_order_source_mod.plan_window_order_source_probes(
            current_source,
            function=function,
            fallback_leads=window_order_fallback.get("leads") or [],
            source_attributions=window_order_source_attributions,
            max_probes=max_count,
        )
        source_role = (
            "initial"
            if source_text is not None and current_source == source_text else "derived"
        )
        window_order_probe_planner_runs.append({
            "source_role": source_role,
            "lead_diagnostics": planned.lead_diagnostics,
        })
        if source_role == "initial" or not window_order_probe_lead_diagnostics:
            window_order_probe_lead_diagnostics = planned.lead_diagnostics

        if max_count <= 0:
            return []
        legacy_generator = window_order_source_mod.generate_window_order_source_probes
        if (
            getattr(legacy_generator, "__module__", None)
            != window_order_source_mod.__name__
        ):
            return legacy_generator(
                current_source,
                function=function,
                fallback_leads=window_order_fallback.get("leads") or [],
                source_attributions=window_order_source_attributions,
                max_probes=max_count,
            )
        return planned.probes

    def _transform_corpus_probes_for(
        current_source: str,
        *,
        max_count: int,
    ) -> list[Any]:
        if max_count <= 0:
            return []
        out: list[Any] = []
        if auto_transform_families:
            _append_transform_corpus_probes(
                out,
                source_text=current_source,
                function=function,
                unit=unit,
                include=True,
                families=list(auto_transform_families),
                force_phys=effective_force_phys,
                max_probes=max_count,
            )
        if (
            len(out) < max_count
            and (include_transform_corpus or bool(transform_family))
            and not auto_transform_families
        ):
            _append_transform_corpus_probes(
                out,
                source_text=current_source,
                function=function,
                unit=unit,
                include=include_transform_corpus,
                families=transform_family,
                force_phys=effective_force_phys,
                max_probes=max_count,
            )
        return out[:max_count]

    def _generated_select_order_probes_for(
        current_source: str,
        *,
        include_lifetime: bool,
        max_count: int,
    ) -> list[Any]:
        if max_count <= 0:
            return []
        has_window_order_leads = (
            isinstance(window_order_fallback, Mapping)
            and bool(window_order_fallback.get("leads"))
        )
        window_order_reserve = _select_order_window_order_probe_reserve(
            window_order_fallback,
            max_count,
        )
        out = _transform_corpus_probes_for(
            current_source,
            max_count=max(0, max_count - window_order_reserve),
        )
        remaining = max(0, max_count - len(out))
        if has_window_order_leads and remaining:
            out.extend(
                _window_order_source_probes_for(
                    current_source,
                    max_count=remaining,
                )
            )
        remaining = max(0, max_count - len(out))
        if include_lifetime and remaining:
            out.extend(
                generate_lifetime_layout_probes(
                    current_source,
                    function,
                    frame_reservation_bytes=frame_reservation_bytes,
                    max_probes=remaining,
                )
            )
        return out[:max_count]

    probes: list[Any] = []
    if source_text:
        try:
            probes = _generated_select_order_probes_for(
                source_text,
                include_lifetime=True,
                max_count=max_probes,
            )
        finally:
            command_source_restore.restore()
    variants: list[dict] = []
    generated_source_dir: Path | None = None
    beam_campaign_dir: Path | None = None
    beam_ledger_path: Path | None = None
    beam_ledger: dict | None = None
    guard_repair_campaign_dir: Path | None = None
    guard_repair_ledger_path: Path | None = None
    guard_repair_ledger: dict | None = None
    guard_repair_summary: dict[str, Any] = {
        "status": "not-requested",
        "lanes": [],
    }
    candidate_pcdump_by_key: dict[int, str] = {}
    candidate_pcdump_key = 0

    def _mark_command_timeout(message: str) -> None:
        nonlocal timed_out, timeout_error
        timed_out = True
        if timeout_error is None:
            timeout_error = message

    def _is_command_timeout_error(message: object) -> bool:
        if not isinstance(message, str):
            return False
        normalized = message.lower()
        return (
            "budget exhausted before" in normalized
            or "deadline exhausted before" in normalized
        )

    def _remaining_command_timeout(
        action: str,
        *,
        min_seconds: float = 0.1,
    ) -> tuple[float | None, str | None]:
        remaining, error = _timeout_before_deadline(
            command_deadline,
            timeout,
            action,
            min_seconds=min_seconds,
        )
        if error is not None:
            _mark_command_timeout(error)
        return remaining, error

    def _command_budget_exhausted(action: str) -> bool:
        _remaining, error = _remaining_command_timeout(action)
        return error is not None

    def _write_timeout_ledger(path: Path, ledger: dict) -> None:
        _write_select_order_timeout_ledger(
            path,
            ledger,
            timed_out=timed_out,
            timeout_error=timeout_error,
        )

    def _skipped_timeout_summary(kind: str) -> dict[str, Any]:
        return {
            "status": "skipped-timeout",
            "summary": kind,
            "reason": timeout_error or "select-order command budget exhausted",
            "partial": True,
            "timed_out": True,
            "timeout_error": timeout_error,
        }

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
        depth: int | None = None,
        parent_label: str | None = None,
        repair_seed_label: str | None = None,
        chain: list[str] | None = None,
        body_fingerprint: str | None = None,
        diff_fingerprint: str | None = None,
        unit_source: Path | None = None,
        full_unit_source: bool = False,
    ) -> dict:
        nonlocal candidate_pcdump_key
        def _finish_timeout_action() -> str:
            if repair_seed_label is not None:
                return f"finishing select-order guard repair candidate {label}"
            if depth is not None:
                return f"finishing select-order beam candidate {label}"
            return f"finishing select-order candidate {label}"

        candidate_source_text: str | None = None
        candidate_text: str | None = None
        candidate_deadline = command_deadline
        try:
            _remaining, deadline_error = _remaining_command_timeout(
                f"scoring select-order candidate {label}"
            )
            if deadline_error is not None:
                raise TimeoutError(deadline_error)
            if full_unit_source and unit_source is None:
                raise ValueError(
                    "full-unit transform probe requires a resolved unit source"
                )
            match_percent = None
            match_percent_error = None
            structural_guard = None
            structural_guard_error = None
            checkdiff_payload = None
            live_restore_paths = (
                [source_path_for_probes, live_unit_source_for_restore]
                if path.suffix == ".c" else []
            )
            with _source_restore_byte_guards(
                live_restore_paths,
                melee_root=DEFAULT_MELEE_ROOT,
            ):
                if path.suffix == ".txt":
                    candidate_text = path.read_text(encoding="utf-8", errors="replace")
                elif path.suffix == ".c":
                    candidate_source_text, _ = (
                        _prevalidate_lifetime_layout_source_candidate(
                            path,
                            function=function,
                        )
                    )
                    try:
                        compile_timeout, deadline_error = _timeout_before_deadline(
                            candidate_deadline,
                            timeout,
                            f"compiling select-order candidate {label}",
                        )
                        if deadline_error is not None:
                            raise TimeoutError(deadline_error)
                        compile_kwargs = dict(
                            diff_input=DiffInput(
                                label=label,
                                token=str(path),
                                kind="source",
                                path=path,
                            ),
                            function=function,
                            melee_root=DEFAULT_MELEE_ROOT,
                            timeout=compile_timeout,
                        )
                        if unit_source is not None:
                            compile_kwargs["unit_source"] = unit_source
                        candidate_text = compile_source_variant(**compile_kwargs)
                        if not isinstance(candidate_text, str):
                            raise RuntimeError(
                                "source compile did not return candidate pcdump text"
                            )
                    except CompileFailure as exc:
                        detail = str(exc)
                        if (
                            exc.returncode == 3
                            and "not found in pcdump" in detail
                        ):
                            raise _MalformedSourceCandidate(
                                (
                                    f"{detail}; compiled probe pcdump omitted the "
                                    f"target function. Source retained at {path}"
                                ),
                                source_hunk=_compact_source_hunk_for_function(
                                    candidate_source_text,
                                    function,
                                ),
                            ) from exc
                        raise
                else:
                    raise ValueError(f"expected .txt pcdump or .c source, got {path}")
                if path.suffix == ".c" and (score_match_percent or proof_force_map):
                    status = (
                        _make_real_score_status("select-order-search", label)
                        if not json_out
                        else None
                    )
                    match_kwargs = dict(
                        path=path,
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                        deadline=candidate_deadline,
                        status=status,
                        include_structural_guard=bool(proof_force_map),
                    )
                    if full_unit_source:
                        match_kwargs["full_unit_source"] = True
                    real_score = _select_order_source_score(**match_kwargs)
                    match_percent = real_score.match_percent
                    match_percent_error = real_score.match_percent_error
                    structural_guard = real_score.structural_guard
                    structural_guard_error = real_score.structural_guard_error
                    checkdiff_payload = real_score.checkdiff_payload
                    for score_error in (
                        match_percent_error,
                        structural_guard_error,
                    ):
                        if _is_command_timeout_error(score_error):
                            _mark_command_timeout(str(score_error))
                            break
            if candidate_text is None:
                raise RuntimeError("candidate pcdump unavailable after scoring")
            try:
                candidate_sig = pressure_signature_from_pcdump(
                    candidate_text,
                    function,
                    pairs=target_orders,
                    class_id=class_id,
                )
            except ValueError as exc:
                if path.suffix == ".c":
                    raise _MalformedSourceCandidate(
                        f"{exc}; compiled probe pcdump omitted the target "
                        f"function. Source retained at {path}",
                        source_hunk=_compact_source_hunk_for_function(
                            candidate_source_text or path.read_text(
                                encoding="utf-8",
                                errors="replace",
                            ),
                            function,
                        ),
                    ) from exc
                raise
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = score_select_order_candidate(
                baseline_text,
                candidate_text,
                function=function,
                target_orders=target_orders,
                class_id=class_id,
                delta=delta,
                match_percent=match_percent,
                proof_force_phys=proof_force_map,
            )
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective.to_dict(),
            }
            if depth is not None:
                variant["depth"] = depth
            if parent_label is not None:
                variant["parent_label"] = parent_label
            if repair_seed_label is not None:
                variant["repair_seed_label"] = repair_seed_label
            if chain:
                variant["chain"] = chain
            if body_fingerprint is not None:
                variant["body_fingerprint"] = body_fingerprint
            if diff_fingerprint is not None:
                variant["diff_fingerprint"] = diff_fingerprint
            probe_payload = candidate_probe_by_label.get(label)
            if probe_payload is not None:
                variant["probe"] = probe_payload
            if match_percent_error is not None:
                variant["match_percent_error"] = match_percent_error
            if structural_guard is not None:
                variant["structural_guard"] = structural_guard
            if structural_guard_error is not None:
                variant["structural_guard_error"] = structural_guard_error
            if checkdiff_payload is not None:
                variant["_checkdiff_payload"] = checkdiff_payload
            retained_source_path = (
                source_retained
                if source_retained is not None
                else path if path.suffix == ".c" else None
            )
            if retained_source_path is not None:
                variant["source_retained"] = str(retained_source_path)
                if path.suffix == ".c" and candidate_text is not None:
                    pcdump_retained = path.with_suffix(".pcdump.txt")
                    try:
                        pcdump_retained.write_text(
                            candidate_text,
                            encoding="utf-8",
                        )
                        variant["pcdump_path"] = str(pcdump_retained)
                        variant["objective"]["pcdump_path"] = str(pcdump_retained)
                    except OSError as exc:
                        variant["pcdump_retention_error"] = str(exc)
            target_score = _select_order_variant_target_score(variant)
            if target_score is not None:
                variant["target_score"] = target_score
            candidate_pcdump_key += 1
            variant["_pcdump_key"] = candidate_pcdump_key
            candidate_pcdump_by_key[candidate_pcdump_key] = candidate_text
            _remaining_command_timeout(_finish_timeout_action())
            variants.append(variant)
            return variant
        except Exception as exc:
            failed_status = "failed"
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            if malformed_source:
                failed_status = "malformed-source"
            elif isinstance(exc, TimeoutError):
                failed_status = "timeout"
                _mark_command_timeout(str(exc))
            elif isinstance(exc, CompileFailure) or (
                path.suffix == ".c" and "not found in pcdump" in str(exc)
            ):
                failed_status = "build-failed"
            failed = {
                "label": label,
                "operator": operator,
                "status": failed_status,
                "path": str(path),
                "error": str(exc),
            }
            if depth is not None:
                failed["depth"] = depth
            if parent_label is not None:
                failed["parent_label"] = parent_label
            if repair_seed_label is not None:
                failed["repair_seed_label"] = repair_seed_label
            if chain:
                failed["chain"] = chain
            if body_fingerprint is not None:
                failed["body_fingerprint"] = body_fingerprint
            if diff_fingerprint is not None:
                failed["diff_fingerprint"] = diff_fingerprint
            probe_payload = candidate_probe_by_label.get(label)
            if probe_payload is not None:
                failed["probe"] = probe_payload
            if source_retained is not None:
                failed["source_retained"] = str(source_retained)
            elif path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            elif path.suffix == ".c":
                hunk_source = candidate_source_text
                if hunk_source is None and path.exists():
                    try:
                        hunk_source = path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    except OSError:
                        hunk_source = None
                if hunk_source is not None:
                    failed["source_hunk"] = _compact_source_hunk_for_function(
                        hunk_source,
                        function,
                    )
            if isinstance(exc, _SourceRestoreBytesError) and exc.backup_path is not None:
                failed["restore_backup_path"] = str(exc.backup_path)
            _remaining_command_timeout(_finish_timeout_action())
            variants.append(failed)
            return failed

    candidate_probe_by_label: dict[str, dict] = {}
    provenance_values = probe_provenance or []
    for index, spec in enumerate(candidates or []):
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        if label in explicit_guard_repair_seed_labels:
            raise typer.BadParameter(
                f"duplicate candidate/guard repair seed label: {label}"
            )
        if _command_budget_exhausted(f"scoring manual candidate {label}"):
            break
        if index < len(provenance_values):
            candidate_probe_by_label[label] = {
                "label": label,
                "operator": operator,
                "description": "User-supplied candidate provenance.",
                "provenance": _parse_probe_provenance(provenance_values[index]),
            }
        _score_candidate(label=label, operator=operator, path=path)

    for seed_spec in explicit_guard_repair_seed_specs:
        label = seed_spec["label"]
        operator = seed_spec["operator"]
        path = Path(seed_spec["path"])
        if _command_budget_exhausted(f"scoring guard repair seed {label}"):
            break
        candidate_probe_by_label[label] = {
            "label": label,
            "operator": operator,
            "description": "User-supplied protected guard-repair seed.",
            "provenance": {
                "kind": "guard-repair-seed",
                "source": "explicit",
            },
        }
        variant = _score_candidate(
            label=label,
            operator=operator,
            path=path,
            source_retained=path,
        )
        variant["guard_repair_explicit_seed"] = True

    if compile_probes and beam_depth <= 0:
        if not probes and not candidates and not explicit_guard_repair_seed_specs:
            typer.echo(
                "source unavailable or no probes generated; pass --source-file "
                "or --candidate OPERATOR=path.",
                err=True,
            )
            command_source_restore.close()
            raise typer.Exit(2)
        if probes:
            generated_source_dir = (
                campaign_dir / "probes"
                if campaign_dir is not None
                else Path(tempfile.mkdtemp(prefix="melee_select_order_"))
            )
            generated_source_dir.mkdir(parents=True, exist_ok=True)
            for probe in probes:
                if _command_budget_exhausted(
                    f"scoring generated select-order probe {probe.label}"
                ):
                    break
                path = generated_source_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                candidate_probe_by_label[probe.label] = probe.to_dict()
                full_unit_source = _probe_requires_full_unit_source(probe)
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                    source_retained=path,
                    unit_source=_full_unit_source_for_probe(
                        probe,
                        source_path_for_probes,
                    ),
                    full_unit_source=full_unit_source,
                )

    fallback_leads = (
        window_order_fallback.get("leads")
        if isinstance(window_order_fallback, Mapping) else []
    )
    window_order_probe_diagnostics = {
        "fallback_leads": len(fallback_leads) if isinstance(fallback_leads, list) else 0,
        "source_attributed_leads": _select_order_source_attributed_fallback_lead_count(
            fallback_leads,
            window_order_source_attributions,
        ),
        "listed_source_probes": sum(
            1 for probe in probes
            if getattr(probe, "operator", None) == "window-order-source-steering"
        ),
        "lead_diagnostics": window_order_probe_lead_diagnostics,
        "planner_runs": window_order_probe_planner_runs[:8],
        "note": (
            "Generic window-order source probes require a unique movable local "
            "assignment; assignable float local product owners may materialize "
            "owner-split probes. Ranked local-owner and indexed-byte spans are "
            "materialized when they have safe executable source anchors; "
            "otherwise per-candidate terminal reasons are reported."
        ),
    }

    if beam_depth > 0:
        if beam_width <= 0:
            raise typer.BadParameter("--beam-width must be positive")
        if not source_text:
            typer.echo(
                "source unavailable; pass --source-file for --beam-depth.",
                err=True,
            )
            raise typer.Exit(2)
        beam_campaign_dir = (
            campaign_dir
            if campaign_dir is not None
            else Path(tempfile.mkdtemp(prefix="melee_select_order_beam_"))
        )
        beam_campaign_dir.mkdir(parents=True, exist_ok=True)
        (beam_campaign_dir / "seed.c").write_text(source_text)
        beam_ledger_path = beam_campaign_dir / "ledger.json"
        beam_ledger = {
            "function": function,
            "target_orders": [list(pair) for pair in target_orders],
            "class_id": class_id,
            "baseline_cache": baseline_cache,
            "beam_depth": beam_depth,
            "beam_width": beam_width,
            "ranking": (
                "target select-order objective, final match percent tiebreaker"
                if proof_force_map
                else "final match percent first, then target select-order objective"
            ),
            "window_order_fallback": window_order_fallback,
            "window_order_probe_diagnostics": window_order_probe_diagnostics,
            "entries": [],
            "deduped": [],
            "stop_condition": None,
        }
        seen_body: set[str] = set()
        seen_diff: set[str] = set()
        seed_body, seed_diff = _select_order_source_fingerprints(
            base_source=source_text,
            candidate_source=source_text,
            function=function,
        )
        seen_body.add(seed_body)
        seen_diff.add(seed_diff)
        frontier: list[dict] = [{
            "label": "seed",
            "source_text": source_text,
            "chain": [],
        }]
        counter = 0
        for depth in range(1, beam_depth + 1):
            if _command_budget_exhausted(f"starting select-order beam depth {depth}"):
                beam_ledger["stop_condition"] = "timeout"
                break
            round_ok: list[tuple[dict, str]] = []
            round_dir = beam_campaign_dir / f"depth-{depth:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            for parent in frontier:
                if timed_out:
                    break
                parent_source = str(parent["source_text"])
                parent_label = str(parent["label"])
                parent_chain = list(parent.get("chain") or [])
                for probe in _generated_select_order_probes_for(
                    parent_source,
                    include_lifetime=True,
                    max_count=max_probes,
                ):
                    if _command_budget_exhausted(
                        f"scoring select-order beam depth {depth}"
                    ):
                        break
                    body_hash, diff_hash = _select_order_source_fingerprints(
                        base_source=source_text,
                        candidate_source=probe.source_text,
                        function=function,
                    )
                    if body_hash in seen_body or diff_hash in seen_diff:
                        beam_ledger["deduped"].append({
                            "depth": depth,
                            "parent_label": parent_label,
                            "probe_label": probe.label,
                            "body_fingerprint": body_hash,
                            "diff_fingerprint": diff_hash,
                        })
                        continue
                    seen_body.add(body_hash)
                    seen_diff.add(diff_hash)
                    counter += 1
                    label = (
                        f"d{depth}-{counter:04d}-"
                        f"{_select_order_safe_label(probe.label)}"
                    )
                    path = round_dir / f"{label}.c"
                    path.write_text(probe.source_text)
                    chain = [*parent_chain, probe.label]
                    probe_payload = probe.to_dict()
                    probe_payload["parent_label"] = parent_label
                    probe_payload["chain"] = chain
                    candidate_probe_by_label[label] = probe_payload
                    variant = _score_candidate(
                        label=label,
                        operator=probe.operator,
                        path=path,
                        source_retained=path,
                        depth=depth,
                        parent_label=parent_label,
                        chain=chain,
                        body_fingerprint=body_hash,
                        diff_fingerprint=diff_hash,
                    )
                    entry = {
                        "label": label,
                        "depth": depth,
                        "parent_label": parent_label,
                        "chain": chain,
                        "status": variant.get("status"),
                        "path": str(path),
                        "body_fingerprint": body_hash,
                        "diff_fingerprint": diff_hash,
                        "match_percent": (
                            (variant.get("objective") or {}).get("match_percent")
                        ),
                        "objective": variant.get("objective"),
                        "structural_guard": variant.get("structural_guard"),
                        "structural_guard_error": variant.get(
                            "structural_guard_error"
                        ),
                        "error": variant.get("error"),
                    }
                    beam_ledger["entries"].append(entry)
                    if variant.get("status") == "ok":
                        round_ok.append((variant, probe.source_text))
                if timed_out:
                    break
            if timed_out:
                beam_ledger["stop_condition"] = "timeout"
                break
            if proof_force_map:
                selected = rank_select_order_candidates(
                    [variant for variant, _source in round_ok]
                )[:beam_width]
            else:
                selected = _rank_select_order_candidates_real_first(
                    [variant for variant, _source in round_ok]
                )[:beam_width]
            selected_labels = {variant["label"] for variant in selected}
            frontier = [
                {
                    "label": variant["label"],
                    "source_text": source,
                    "chain": variant.get("chain") or [],
                }
                for variant, source in round_ok
                if variant["label"] in selected_labels
            ]
            if not frontier:
                beam_ledger["stop_condition"] = "frontier-empty"
                break
        if beam_ledger["stop_condition"] is None:
            beam_ledger["stop_condition"] = (
                "depth-exhausted" if beam_ledger["entries"] else "no-beam-probes"
            )
        _write_timeout_ledger(beam_ledger_path, beam_ledger)

    if effective_guard_repair_depth > 0 and proof_force_map:
        current_ranked = (
            rank_select_order_candidates(variants)
            if proof_force_map
            else _rank_select_order_candidates_real_first(variants)
        )
        explicit_ranked = [
            variant for variant in current_ranked
            if variant.get("guard_repair_explicit_seed") is True
        ]
        repair_seeds = _select_order_guard_repair_seed_variants(
            explicit_ranked,
            force_phys=proof_force_map,
            max_seeds=guard_repair_width,
        )
        if len(repair_seeds) < guard_repair_width:
            selected_labels = {
                str(seed.get("label"))
                for seed in repair_seeds
                if isinstance(seed.get("label"), str)
            }
            fallback_ranked = [
                variant for variant in current_ranked
                if str(variant.get("label")) not in selected_labels
            ]
            repair_seeds.extend(
                _select_order_guard_repair_seed_variants(
                    fallback_ranked,
                    force_phys=proof_force_map,
                    max_seeds=guard_repair_width - len(repair_seeds),
                )
            )
        if repair_seeds:
            base_repair_dir = (
                campaign_dir
                if campaign_dir is not None
                else beam_campaign_dir
            )
            guard_repair_campaign_dir = (
                (base_repair_dir / "guard-repair")
                if base_repair_dir is not None
                else Path(tempfile.mkdtemp(prefix="melee_select_order_guard_repair_"))
            )
            guard_repair_campaign_dir.mkdir(parents=True, exist_ok=True)
            guard_repair_ledger_path = guard_repair_campaign_dir / "ledger.json"
            guard_repair_ledger = {
                "function": function,
                "target_orders": [list(pair) for pair in target_orders],
                "class_id": class_id,
                "effective_depth": effective_guard_repair_depth,
                "width": guard_repair_width,
                "max_probes": max_probes,
                "ranking": (
                    "guard accepted, protected force-phys hits, normalized "
                    "diff/frame repair, force-phys distance, match percent"
                ),
                "explicit_seed_specs": explicit_guard_repair_seed_specs,
                "seeds": [],
                "entries": [],
                "reconciliation_frontier": [],
                "deduped": [],
                "stop_condition": None,
                "timed_out": False,
                "timeout_error": None,
                "partial": False,
            }
            seen_body: set[str] = set()
            seen_diff: set[str] = set()
            frontier: list[dict[str, Any]] = []
            seed_sources_for_crossover: list[dict[str, Any]] = []
            for seed in repair_seeds:
                source_path_raw = seed.get("source_retained") or seed.get("path")
                if not isinstance(source_path_raw, str):
                    continue
                source_path = Path(source_path_raw)
                try:
                    seed_source = source_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError as exc:
                    guard_repair_ledger["deduped"].append({
                        "seed_label": seed.get("label"),
                        "reason": f"source-unreadable: {exc}",
                        "source_retained": source_path_raw,
                    })
                    continue
                protected_hits = _select_order_force_phys_hit_registers(seed)
                seed_summary = _select_order_guard_repair_candidate_summary(seed) or {}
                complement_targets = _select_order_complement_target_summary(
                    force_phys=proof_force_map,
                    seed_candidate=seed_summary,
                    protected_registers=protected_hits,
                )
                seed_entry = {
                    "label": seed.get("label"),
                    "path": seed.get("path"),
                    "source_retained": source_path_raw,
                    "chain": list(seed.get("chain") or []),
                    "protected_force_phys_hits": protected_hits,
                    "protected_complement_targets": complement_targets,
                    "seed_source": (
                        "explicit"
                        if seed.get("guard_repair_explicit_seed") is True
                        else "ranked-variant"
                    ),
                    "guard": seed.get("structural_guard"),
                    "objective": seed.get("objective"),
                    "summary": seed_summary,
                }
                guard_repair_ledger["seeds"].append(seed_entry)
                seed_sources_for_crossover.append({
                    "label": seed.get("label"),
                    "source_text": seed_source,
                    "protected_hits": protected_hits,
                })
                frontier.append({
                    "label": seed.get("label"),
                    "repair_seed_label": seed.get("label"),
                    "source_text": seed_source,
                    "chain": list(seed.get("chain") or []),
                    "protected_hits": protected_hits,
                    "protected_complement_targets": complement_targets,
                })

            counter = 0
            for depth in range(1, effective_guard_repair_depth + 1):
                if _command_budget_exhausted(
                    f"starting select-order guard repair depth {depth}"
                ):
                    guard_repair_ledger["stop_condition"] = "timeout"
                    break
                round_ok: list[
                    tuple[
                        dict,
                        str,
                        Mapping[str, int],
                        str,
                        Mapping[str, Mapping[str, Any]],
                    ]
                ] = []
                round_dir = guard_repair_campaign_dir / f"depth-{depth:02d}"
                round_dir.mkdir(parents=True, exist_ok=True)
                crossover_probes = (
                    _select_order_source_hunk_crossover_probes(
                        base_source=source_text,
                        seed_sources=seed_sources_for_crossover,
                        function=function,
                        max_probes=max_probes,
                    )
                    if depth == 1 and source_text
                    else []
                )
                for probe in crossover_probes:
                    if _command_budget_exhausted(
                        f"scoring select-order guard repair crossover depth {depth}"
                    ):
                        break
                    raw_protected = (
                        (probe.provenance or {}).get("protected_force_phys_hits")
                        if isinstance(probe.provenance, Mapping)
                        else {}
                    )
                    protected_hits = {
                        str(ig_idx): int(phys)
                        for ig_idx, phys in dict(raw_protected or {}).items()
                        if str(ig_idx).lstrip("-").isdigit()
                    }
                    parent_label = "cross-neighborhood"
                    repair_seed_label = "cross-neighborhood"
                    chain = [probe.label]
                    body_hash, diff_hash = _select_order_source_fingerprints(
                        base_source=source_text,
                        candidate_source=probe.source_text,
                        function=function,
                    )
                    if body_hash in seen_body or diff_hash in seen_diff:
                        guard_repair_ledger["deduped"].append({
                            "depth": depth,
                            "seed_label": parent_label,
                            "probe_label": probe.label,
                            "body_fingerprint": body_hash,
                            "diff_fingerprint": diff_hash,
                        })
                    else:
                        seen_body.add(body_hash)
                        seen_diff.add(diff_hash)
                        counter += 1
                        label = (
                            f"gr{depth}-{counter:04d}-"
                            f"{_select_order_safe_label(probe.label)}"
                        )
                        path = round_dir / f"{label}.c"
                        path.write_text(probe.source_text)
                        probe_payload = probe.to_dict()
                        probe_payload["parent_label"] = parent_label
                        probe_payload["repair_seed_label"] = repair_seed_label
                        probe_payload["chain"] = chain
                        candidate_probe_by_label[label] = probe_payload
                        variant = _score_candidate(
                            label=label,
                            operator=probe.operator,
                            path=path,
                            source_retained=path,
                            depth=depth,
                            parent_label=parent_label,
                            repair_seed_label=repair_seed_label,
                            chain=chain,
                            body_fingerprint=body_hash,
                            diff_fingerprint=diff_hash,
                        )
                        entry = {
                            "label": label,
                            "depth": depth,
                            "seed_label": parent_label,
                            "repair_seed_label": repair_seed_label,
                            "chain": chain,
                            "status": variant.get("status"),
                            "path": str(path),
                            "body_fingerprint": body_hash,
                            "diff_fingerprint": diff_hash,
                            "protected_force_phys_hits": protected_hits,
                            "protected_complement_targets": (
                                _select_order_default_complement_targets(
                                    force_phys=proof_force_map,
                                    protected_registers=protected_hits,
                                )
                            ),
                            "match_percent": (
                                (variant.get("objective") or {}).get(
                                    "match_percent"
                                )
                            ),
                            "objective": variant.get("objective"),
                            "structural_guard": variant.get("structural_guard"),
                            "structural_guard_error": variant.get(
                                "structural_guard_error"
                            ),
                            "error": variant.get("error"),
                            "probe": variant.get("probe"),
                            "source_hunk": variant.get("source_hunk"),
                            "protected_complement": (
                                _select_order_guard_repair_entry_protected_complement(
                                    variant,
                                    force_phys=proof_force_map,
                                    protected_hits=protected_hits,
                                )
                            ),
                        }
                        protected_preservation = (
                            _select_order_protected_register_preservation(
                                variant,
                                protected_hits,
                            )
                        )
                        variant["protected_preservation"] = protected_preservation
                        entry.update(protected_preservation)
                        guard_repair_ledger["entries"].append(entry)
                        if variant.get("status") == "ok":
                            round_ok.append((
                                variant,
                                probe.source_text,
                                protected_hits,
                                repair_seed_label,
                                _select_order_default_complement_targets(
                                    force_phys=proof_force_map,
                                    protected_registers=protected_hits,
                                ),
                            ))
                if timed_out:
                    guard_repair_ledger["stop_condition"] = "timeout"
                    break
                for parent in frontier:
                    if timed_out:
                        break
                    parent_source = str(parent["source_text"])
                    parent_label = str(parent["label"])
                    repair_seed_label = str(
                        parent.get("repair_seed_label") or parent_label
                    )
                    parent_chain = list(parent.get("chain") or [])
                    protected_hits = dict(parent.get("protected_hits") or {})
                    protected_complement_targets = dict(
                        parent.get("protected_complement_targets") or {}
                    )
                    parent_reconciliation_seed = parent.get("reconciliation_seed")
                    targeted_plan = parent.get(
                        "targeted_interference_source_transforms"
                    )
                    targeted_delta = (
                        _select_order_materializable_targeted_interference_delta(
                            targeted_plan
                            if isinstance(targeted_plan, Mapping) else None
                        )
                    )
                    targeted_probes: list[Any] = []
                    if targeted_delta is not None:
                        _append_transform_corpus_probes(
                            targeted_probes,
                            source_text=parent_source,
                            function=function,
                            unit=unit,
                            include=True,
                            families=["coloring_register_steering"],
                            force_phys=effective_force_phys,
                            max_probes=max_probes,
                            node_set_delta=targeted_delta,
                        )
                        if isinstance(targeted_plan, Mapping):
                            targeted_probes = [
                                _select_order_tag_targeted_interference_probe(
                                    probe,
                                    plan=targeted_plan,
                                )
                                for probe in targeted_probes
                            ]
                    subtractive_probes = (
                        _select_order_subtractive_source_hunk_repair_probes(
                            base_source=source_text,
                            downhill_source=parent_source,
                            function=function,
                            protected_hits=protected_hits,
                            max_probes=max(0, max_probes - len(targeted_probes)),
                        )
                        if source_text
                        else []
                    )
                    generated_probes = _generated_select_order_probes_for(
                        parent_source,
                        include_lifetime=True,
                        max_count=max(
                            0,
                            max_probes
                            - len(targeted_probes)
                            - len(subtractive_probes),
                        ),
                    )
                    for probe in [
                        *targeted_probes,
                        *subtractive_probes,
                        *generated_probes,
                    ]:
                        if _command_budget_exhausted(
                            f"scoring select-order guard repair depth {depth}"
                        ):
                            break
                        body_hash, diff_hash = _select_order_source_fingerprints(
                            base_source=source_text or parent_source,
                            candidate_source=probe.source_text,
                            function=function,
                        )
                        if body_hash in seen_body or diff_hash in seen_diff:
                            guard_repair_ledger["deduped"].append({
                                "depth": depth,
                                "seed_label": parent_label,
                                "probe_label": probe.label,
                                "body_fingerprint": body_hash,
                                "diff_fingerprint": diff_hash,
                            })
                            continue
                        seen_body.add(body_hash)
                        seen_diff.add(diff_hash)
                        counter += 1
                        label = (
                            f"gr{depth}-{counter:04d}-"
                            f"{_select_order_safe_label(probe.label)}"
                        )
                        path = round_dir / f"{label}.c"
                        path.write_text(probe.source_text)
                        chain = [*parent_chain, probe.label]
                        probe_payload = probe.to_dict()
                        probe_payload["parent_label"] = parent_label
                        probe_payload["repair_seed_label"] = repair_seed_label
                        probe_payload["chain"] = chain
                        candidate_probe_by_label[label] = probe_payload
                        variant = _score_candidate(
                            label=label,
                            operator=probe.operator,
                            path=path,
                            source_retained=path,
                            depth=depth,
                            parent_label=parent_label,
                            repair_seed_label=repair_seed_label,
                            chain=chain,
                            body_fingerprint=body_hash,
                            diff_fingerprint=diff_hash,
                        )
                        entry = {
                            "label": label,
                            "depth": depth,
                            "seed_label": parent_label,
                            "repair_seed_label": repair_seed_label,
                            "chain": chain,
                            "status": variant.get("status"),
                            "path": str(path),
                            "body_fingerprint": body_hash,
                            "diff_fingerprint": diff_hash,
                            "protected_force_phys_hits": protected_hits,
                            "protected_complement_targets": (
                                protected_complement_targets
                            ),
                            "match_percent": (
                                (variant.get("objective") or {}).get(
                                    "match_percent"
                                )
                            ),
                            "objective": variant.get("objective"),
                            "structural_guard": variant.get("structural_guard"),
                            "structural_guard_error": variant.get(
                                "structural_guard_error"
                            ),
                            "error": variant.get("error"),
                            "probe": variant.get("probe"),
                            "source_hunk": variant.get("source_hunk"),
                            "protected_complement": (
                                _select_order_guard_repair_entry_protected_complement(
                                    variant,
                                    force_phys=proof_force_map,
                                    protected_hits=protected_hits,
                                    complement_targets=protected_complement_targets,
                                )
                            ),
                        }
                        protected_preservation = (
                            _select_order_protected_register_preservation(
                                variant,
                                protected_hits,
                            )
                        )
                        variant["protected_preservation"] = protected_preservation
                        entry.update(protected_preservation)
                        if isinstance(parent_reconciliation_seed, Mapping):
                            entry["reconciliation_seed"] = dict(
                                parent_reconciliation_seed
                            )
                        guard_repair_ledger["entries"].append(entry)
                        if variant.get("status") == "ok":
                            round_ok.append((
                                variant,
                                probe.source_text,
                                protected_hits,
                                repair_seed_label,
                                protected_complement_targets,
                            ))
                    if timed_out:
                        break
                if timed_out:
                    guard_repair_ledger["stop_condition"] = "timeout"
                    break
                ranked_round = sorted(
                    round_ok,
                    key=lambda item: _select_order_guard_repair_variant_sort_key(
                        item[0],
                        protected_hits=item[2],
                    ),
                    reverse=True,
                )
                selected_items = ranked_round[:guard_repair_width]
                frontier = []
                selected_labels: set[str] = set()
                for (
                    variant,
                    candidate_source,
                    protected_hits,
                    repair_seed_label,
                    protected_complement_targets,
                ) in selected_items:
                    label = str(variant.get("label"))
                    selected_labels.add(label)
                    recovery = (
                        _select_order_guard_repair_reconciliation_frontier_entry(
                            variant,
                            function=function,
                            class_id=class_id,
                            candidate_source=candidate_source,
                            force_phys=proof_force_map,
                            protected_hits=protected_hits,
                            complement_targets=protected_complement_targets,
                            repair_seed_label=repair_seed_label,
                            depth=depth,
                            window_order_source_attributions=(
                                window_order_source_attributions
                            ),
                            window_order_probe_diagnostics=(
                                window_order_probe_diagnostics
                            ),
                        )
                    )
                    if recovery is not None:
                        frontier.append(recovery["frontier"])
                        guard_repair_ledger["reconciliation_frontier"].append(
                            recovery["ledger"]
                        )
                        continue
                    frontier.append({
                        "label": variant.get("label"),
                        "repair_seed_label": repair_seed_label,
                        "source_text": candidate_source,
                        "chain": variant.get("chain") or [],
                        "protected_hits": protected_hits,
                        "protected_complement_targets": protected_complement_targets,
                    })
                reconciliation_frontier: list[dict[str, Any]] = []
                for (
                    variant,
                    candidate_source,
                    protected_hits,
                    repair_seed_label,
                    protected_complement_targets,
                ) in ranked_round:
                    label = str(variant.get("label"))
                    if label in selected_labels:
                        continue
                    recovery = (
                        _select_order_guard_repair_reconciliation_frontier_entry(
                            variant,
                            function=function,
                            class_id=class_id,
                            candidate_source=candidate_source,
                            force_phys=proof_force_map,
                            protected_hits=protected_hits,
                            complement_targets=protected_complement_targets,
                            repair_seed_label=repair_seed_label,
                            depth=depth,
                            window_order_source_attributions=(
                                window_order_source_attributions
                            ),
                            window_order_probe_diagnostics=(
                                window_order_probe_diagnostics
                            ),
                        )
                    )
                    if recovery is None:
                        continue
                    recovery_frontier = recovery["frontier"]
                    if any(
                        item.get("label") == recovery_frontier.get("label")
                        and item.get("protected_hits")
                        == recovery_frontier.get("protected_hits")
                        for item in frontier
                    ):
                        continue
                    reconciliation_frontier.append(recovery_frontier)
                    guard_repair_ledger["reconciliation_frontier"].append(
                        recovery["ledger"]
                    )
                    selected_labels.add(label)
                    if len(reconciliation_frontier) >= guard_repair_width:
                        break
                frontier.extend(reconciliation_frontier)
                if not frontier:
                    guard_repair_ledger["stop_condition"] = "frontier-empty"
                    break
            if guard_repair_ledger["stop_condition"] is None:
                guard_repair_ledger["stop_condition"] = (
                    "depth-exhausted"
                    if guard_repair_ledger["entries"] else "no-repair-probes"
                )
            _write_timeout_ledger(guard_repair_ledger_path, guard_repair_ledger)

    if beam_depth > 0:
        if proof_force_map:
            ranked_variants = rank_select_order_candidates(variants)
            ranking = "target select-order objective, final match percent tiebreaker"
        else:
            ranked_variants = _rank_select_order_candidates_real_first(variants)
            ranking = "final match percent first, then target select-order objective"
    else:
        ranked_variants = rank_select_order_candidates(variants)
        ranking = "target select-order objective, final match percent tiebreaker"

    if timed_out:
        residual_count = 0
    elif residual_first_divergence_top is None:
        residual_count = (
            3
            if proof_force_map
            and not any(
                variant.get("status") == "ok"
                and (variant.get("objective") or {}).get("force_phys_satisfied") is True
                for variant in ranked_variants
            )
            else 0
        )
    else:
        residual_count = residual_first_divergence_top

    residual_top_variants: list[dict] = []
    if residual_count and proof_force_map:
        residual_top_variants = [
            variant for variant in ranked_variants
            if variant.get("status") == "ok"
        ][:residual_count]
    diagnostic_buckets: dict[str, list[dict[str, Any]]] = {}
    if proof_force_map:
        diagnostic_buckets = _select_order_diagnostic_buckets(
            ranked_variants,
            force_phys=proof_force_map,
            function=function,
            global_top=residual_top_variants,
        )
    residual_labels = _select_order_residual_variant_labels_from_buckets(
        diagnostic_buckets
    )
    residual_labels.update(
        label for label in (
            variant.get("label") for variant in residual_top_variants
        )
        if isinstance(label, str)
    )
    if residual_labels and proof_force_map:
        residual_variants = [
            variant for variant in ranked_variants
            if variant.get("status") == "ok"
            and isinstance(variant.get("label"), str)
            and variant["label"] in residual_labels
        ]
        for variant in residual_variants:
            pcdump_key = variant.get("_pcdump_key")
            candidate_pcdump = (
                candidate_pcdump_by_key.get(pcdump_key)
                if isinstance(pcdump_key, int) else None
            )
            if candidate_pcdump is None:
                variant["residual_analysis"] = {
                    "status": "abstain",
                    "reason": "candidate pcdump was not retained for residual analysis",
                    "candidate_label": variant.get("label"),
                    "rank": variant.get("rank"),
                    "class_id": class_id,
                    "force_phys": {
                        str(k): v for k, v in sorted(proof_force_map.items())
                    },
                    "source_retained": variant.get("source_retained"),
                }
                continue
            variant["residual_analysis"] = (
                _select_order_candidate_residual_first_divergence(
                    variant=variant,
                    candidate_pcdump=candidate_pcdump,
                    function=function,
                    class_id=class_id,
                    force_phys=proof_force_map,
                    source_retained=variant.get("source_retained"),
                )
            )
    window_order_probe_diagnostics = (
        _select_order_refresh_window_order_probe_diagnostics(
            window_order_probe_diagnostics,
            ranked_variants,
        )
    )
    source_bridge_summary: dict[str, Any] | None = None
    terminal_exhaustion_summary: dict[str, Any] | None = None
    source_restored, source_restore_error = _select_order_close_source_restore(
        command_source_restore
    )

    def _json_success_payload() -> dict[str, Any]:
        return {
            "function": function,
            "target_orders": [list(pair) for pair in target_orders],
            "class_id": class_id,
            "status": "timeout" if timed_out else "ok",
            "timed_out": timed_out,
            "partial": timed_out,
            "timeout_seconds": timeout if timeout and timeout > 0 else None,
            "timeout_error": timeout_error,
            "source_restored": source_restored,
            "source_restore_error": source_restore_error,
            "ranking": ranking,
            "auto_transform_families": list(auto_transform_families),
            "window_order_fallback": window_order_fallback,
            "window_order_source_attributions": {
                str(key): _solve_source_attribution_dict(value)
                for key, value in window_order_source_attributions.items()
            },
            "window_order_probe_diagnostics": window_order_probe_diagnostics,
            "diagnostic_buckets": diagnostic_buckets,
            "baseline": baseline.to_dict(),
            "baseline_pcdump_path": str(baseline_path),
            "baseline_pcdump_source": baseline_pcdump_source,
            "baseline_cache": baseline_cache,
            "source": source_label,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "beam_campaign_dir": (
                str(beam_campaign_dir) if beam_campaign_dir is not None else None
            ),
            "beam_ledger": (
                str(beam_ledger_path) if beam_ledger_path is not None else None
            ),
            "guard_repair_campaign_dir": (
                str(guard_repair_campaign_dir)
                if guard_repair_campaign_dir is not None else None
            ),
            "guard_repair_ledger": (
                str(guard_repair_ledger_path)
                if guard_repair_ledger_path is not None else None
            ),
            "guard_repair_seed_specs": explicit_guard_repair_seed_specs,
            "guard_repair_summary": guard_repair_summary,
            "source_bridge_summary": source_bridge_summary,
            "terminal_exhaustion_summary": terminal_exhaustion_summary,
            "probes": [probe.to_dict() for probe in probes],
            "variants": ranked_variants,
        }

    def _json_failure_payload(exc: BaseException) -> dict[str, Any]:
        return {
            "function": function,
            "target_orders": [list(pair) for pair in target_orders],
            "class_id": class_id,
            "status": "failed",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "source_restored": source_restored,
            "source_restore_error": source_restore_error,
            "source": source_label,
            "baseline_pcdump_path": str(baseline_path),
            "baseline_pcdump_source": baseline_pcdump_source,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "beam_campaign_dir": (
                str(beam_campaign_dir) if beam_campaign_dir is not None else None
            ),
            "beam_ledger": (
                str(beam_ledger_path) if beam_ledger_path is not None else None
            ),
            "guard_repair_campaign_dir": (
                str(guard_repair_campaign_dir)
                if guard_repair_campaign_dir is not None else None
            ),
            "guard_repair_ledger": (
                str(guard_repair_ledger_path)
                if guard_repair_ledger_path is not None else None
            ),
            "guard_repair_seed_specs": explicit_guard_repair_seed_specs,
            "guard_repair_summary": guard_repair_summary,
            "source_bridge_summary": source_bridge_summary,
            "probes": [probe.to_dict() for probe in probes],
            "variants": _select_order_public_variants(ranked_variants),
        }

    def _build_source_bridge_summary(
        force_phys_map: Mapping[int, int],
    ) -> dict[str, Any]:
        if timed_out and _command_budget_exhausted(
            "building select-order source bridge summary"
        ):
            return _skipped_timeout_summary("source bridge summary")
        try:
            summary = _select_order_source_bridge_summary(
                ranked_variants=ranked_variants,
                force_phys=force_phys_map,
                window_order_fallback=window_order_fallback,
                window_order_source_attributions=window_order_source_attributions,
                window_order_probe_diagnostics=window_order_probe_diagnostics,
                diagnostic_buckets=diagnostic_buckets,
                function=function,
                base_source_path=source_path_for_probes,
                campaign_dir=campaign_dir,
            )
        except Exception as exc:
            if not timed_out:
                raise
            return {
                "status": "skipped-timeout",
                "reason": timeout_error
                or "select-order command budget exhausted",
                "partial": True,
                "timed_out": True,
                "timeout_error": timeout_error,
                "summary_error": str(exc),
            }
        if timed_out:
            summary = dict(summary)
            summary["partial"] = True
            summary["timed_out"] = True
            summary["timeout_error"] = timeout_error
        return summary

    if not source_restored:
        restore_exc = RuntimeError(
            source_restore_error or "source restore verification failed"
        )
        if json_out:
            print(json.dumps(
                _select_order_json_safe(_json_failure_payload(restore_exc)),
                indent=2,
            ))
            raise typer.Exit(1)
        raise restore_exc

    try:
        if proof_force_map:
            if timed_out and _command_budget_exhausted(
                "building select-order guard repair summary"
            ):
                guard_repair_summary = _skipped_timeout_summary(
                    "guard repair summary"
                )
                guard_repair_summary["lanes"] = []
            else:
                guard_repair_summary = _select_order_guard_repair_summary(
                    ranked_variants,
                    force_phys=proof_force_map,
                    guard_repair_ledger=guard_repair_ledger_path,
                    function=function,
                    target_orders=target_orders,
                    class_id=class_id,
                    window_order_source_attributions=window_order_source_attributions,
                    window_order_probe_diagnostics=window_order_probe_diagnostics,
                )
            source_bridge_summary = _build_source_bridge_summary(proof_force_map)
        else:
            source_bridge_summary = _build_source_bridge_summary({})
        if proof_force_map:
            blocker_targets = {
                second for _, second in target_orders
                if second in proof_force_map
            }
            if not blocker_targets:
                blocker_targets = set(proof_force_map)
            if timed_out and _command_budget_exhausted(
                "building select-order terminal exhaustion summary"
            ):
                terminal_exhaustion_summary = _skipped_timeout_summary(
                    "terminal exhaustion summary"
                )
            else:
                terminal_exhaustion_summary = (
                    _select_order_terminal_exhaustion_summary(
                        ranked_variants=ranked_variants,
                        force_phys=proof_force_map,
                        blocker_targets=blocker_targets,
                        diagnostic_buckets=diagnostic_buckets,
                        source_bridge_summary=source_bridge_summary,
                        timed_out=timed_out,
                        class_id=class_id,
                    )
                )
        for variant in ranked_variants:
            variant.pop("_pcdump_key", None)
            variant.pop("_checkdiff_payload", None)

        if json_out:
            print(json.dumps(
                _select_order_json_safe(_json_success_payload()),
                indent=2,
            ))
            return
    except Exception as exc:
        if json_out:
            print(json.dumps(
                _select_order_json_safe(_json_failure_payload(exc)),
                indent=2,
            ))
            raise typer.Exit(1)
        raise

    print(f"select-order-search - {function}")
    print(
        "target: "
        + ", ".join(f"r{first}<r{second}" for first, second in target_orders)
    )
    print(f"class: {class_id}")
    print(f"ranking: {ranking}")
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if baseline_cache is not None:
        source_mtime = baseline_cache.get("source_mtime")
        cache_mtime = baseline_cache.get("cache_mtime")
        print(
            "baseline cache: "
            f"fresh={baseline_cache.get('fresh')} "
            f"src_mtime={source_mtime if source_mtime is not None else '?'} "
            f"cache_mtime={cache_mtime if cache_mtime is not None else '?'}"
        )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    if beam_campaign_dir is not None:
        print(f"beam campaign dir: {beam_campaign_dir}")
    if beam_ledger_path is not None:
        print(f"beam ledger: {beam_ledger_path}")
    if guard_repair_campaign_dir is not None:
        print(f"guard repair campaign dir: {guard_repair_campaign_dir}")
    if guard_repair_ledger_path is not None:
        print(f"guard repair ledger: {guard_repair_ledger_path}")
    if guard_repair_summary.get("status") in {"needs-repair", "repair-found"}:
        lane_text = ", ".join(
            str(lane.get("kind") or lane.get("guard_class"))
            for lane in guard_repair_summary.get("lanes", [])
            if isinstance(lane, Mapping)
        )
        print(
            f"guard repair: {guard_repair_summary.get('status')}"
            + (f" ({lane_text})" if lane_text else "")
        )
    if source_bridge_summary.get("status") == "blocked":
        print(
            "source bridge: blocked via "
            f"{source_bridge_summary.get('dominant_blocker', '?')}"
        )
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            print(render_select_order_variant(variant))
            residual = variant.get("residual_analysis")
            if isinstance(residual, Mapping):
                print(_format_select_order_residual(residual))
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")
