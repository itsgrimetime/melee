from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.mwcc_debug.retained_frontier_triage import (
    RetainedFrontierTriageError,
    render_retained_frontier_text,
    triage_retained_frontiers,
)
from src.search.delta_minimize import (
    DeltaMinimizeConfig,
    DeltaMinimizeError,
    parse_donor_overrides,
    render_delta_minimize_text,
    run_delta_minimize,
)

from ._helpers import *  # noqa: F403
from ._helpers import _CFLAGS


class _SearchRunDirectedPipeline:
    """Bridge byte scoring and directed scoring for `debug search run`."""

    def __init__(self, *, byte_pipeline, directed_pipeline) -> None:
        self._byte_pipeline = byte_pipeline
        self._directed_pipeline = directed_pipeline

    def score_byte(self, art, target):
        return self._byte_pipeline.score_byte(art, target)

    def should_escalate(self, art, ctx) -> bool:
        return True

    def score_directed(self, art, call):
        return self._directed_pipeline.score_directed(art, call)


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "configure.py").is_file() and (path / "src" / "melee").is_dir()


def _find_melee_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if _looks_like_melee_root(candidate):
            return candidate
    return None


def _compute_melee_root() -> Path:
    """Resolve the melee repo root for the command invocation.

    Prefer the current working directory so an editable install launched from a
    matcher worktree operates on that dirty checkout. Fall back to this file's
    repo root when invoked from outside a Melee tree.
    """
    cwd_root = _find_melee_root(Path.cwd())
    if cwd_root is not None:
        return cwd_root

    # tools/melee-agent/src/search/cli.py:
    # parents[0]=search [1]=src [2]=melee-agent [3]=tools [4]=<repo root>
    return Path(__file__).resolve().parents[4]


def _resolve_source_file(path: Path | None, *, melee_root: Path) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    candidates = [expanded]
    if not expanded.is_absolute():
        candidates.append(Path.cwd() / expanded)
        candidates.append(melee_root / expanded)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise typer.BadParameter(f"source file not found: {path}")


def _path_has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _delta_source_candidates(path: Path, *, melee_root: Path) -> tuple[Path, ...]:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return (expanded,)
    candidates = (Path.cwd() / expanded, melee_root / expanded)
    return tuple(dict.fromkeys(candidates))


def _resolve_delta_source_file(path: Path, *, melee_root: Path) -> Path:
    """Resolve one delta parent only after fail-closed symlink validation."""

    for candidate in _delta_source_candidates(path, melee_root=melee_root):
        if _path_has_symlink_component(candidate):
            raise typer.BadParameter(f"source file not found or unsafe: {path}")
        if candidate.is_file():
            return candidate.resolve()
    raise typer.BadParameter(f"source file not found: {path}")


def _resolve_delta_target_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
    if _path_has_symlink_component(candidate) or not candidate.is_file():
        raise typer.BadParameter(f"target file not found or unsafe: {path}")
    return candidate.resolve()


def _resolve_delta_output_dir(path: Path, *, melee_root: Path) -> Path:
    """Resolve an output directory only after checking every path component."""

    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else melee_root / expanded
    if _path_has_symlink_component(candidate):
        raise typer.BadParameter(f"output directory is unsafe: {path}")
    return candidate.resolve()


def _delta_error_message(error: DeltaMinimizeError) -> str:
    if not error.details:
        return error.reason
    details = ", ".join(
        f"{key}={value}" for key, value in sorted(error.details.items())
    )
    return f"{error.reason}: {details}"


def _resolve_optional_plan_source_file(
    plan_source_file: str,
    *,
    melee_root: Path,
) -> Path | None:
    path = Path(plan_source_file)
    candidates = [path]
    if not path.is_absolute():
        candidates.append(melee_root / path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _resolve_structure_source_file(
    function: str,
    source_file: Path | None,
    *,
    melee_root: Path,
) -> Path:
    if source_file is not None:
        resolved = _resolve_source_file(source_file, melee_root=melee_root)
        assert resolved is not None
        return resolved

    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.is_file():
        raise typer.BadParameter(
            "source file was not provided and build/GALE01/report.json was not found"
        )
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse build/GALE01/report.json: {exc}"
        ) from exc

    for unit in report.get("units", []):
        if not isinstance(unit, dict):
            continue
        functions = unit.get("functions") or []
        if not any(
            isinstance(row, dict) and row.get("name") == function for row in functions
        ):
            continue
        unit_name = str(unit.get("name") or "").removeprefix("main/")
        if not unit_name:
            break
        source_rel = unit_name if unit_name.endswith(".c") else f"{unit_name}.c"
        source_path = melee_root / "src" / source_rel
        if source_path.is_file():
            return source_path.resolve()
        raise typer.BadParameter(f"resolved source file not found: {source_path}")

    raise typer.BadParameter(
        f"could not resolve source for {function!r} from build/GALE01/report.json; pass --source-file"
    )


def _resolve_structure_output_dir(
    output_dir: Path | None,
    *,
    function: str,
    melee_root: Path,
) -> Path:
    if output_dir is None:
        return melee_root / "build" / "structure-search" / function
    expanded = output_dir.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.resolve()


def _parse_structure_pure_helpers(
    raw_values: list[str] | None,
) -> dict[str, str] | None:
    helpers: dict[str, str] = {}
    for raw in raw_values or []:
        for item in str(raw).split(","):
            spec = item.strip()
            if not spec:
                continue
            if "=" in spec:
                name, return_type = spec.split("=", 1)
            elif ":" in spec:
                name, return_type = spec.split(":", 1)
            else:
                name, return_type = spec, "s32"
            name = name.strip()
            return_type = return_type.strip() or "s32"
            if not name:
                raise typer.BadParameter(
                    f"invalid --pure-helper value {raw!r}: missing helper name"
                )
            helpers[name] = return_type
    return helpers or None


def _parse_run_seed(raw: str, *, melee_root: Path) -> tuple[str, Path]:
    """Parse a search run seed, optionally preserving an explicit ID."""
    if "=" in raw:
        candidate_id, path_s = raw.split("=", 1)
        candidate_id = candidate_id.strip()
        path = Path(path_s.strip())
    else:
        path = Path(raw.strip())
        candidate_id = path.stem
    if not candidate_id:
        raise typer.BadParameter(f"seed spec {raw!r} has an empty candidate id")
    resolved = _resolve_source_file(path, melee_root=melee_root)
    assert resolved is not None
    return candidate_id, resolved


def _parse_directed_int(raw: str, *, prefix: str = "") -> int:
    value = raw.strip().lower()
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :]
    if not value:
        raise ValueError(f"missing integer in {raw!r}")
    return int(value, 0)


def _parse_directed_class(raw: str) -> int:
    value = raw.strip().lower()
    if value in {"gpr", "r"}:
        return 0
    if value in {"fp", "fpr", "f"}:
        return 1
    if value.startswith("class"):
        value = value[len("class") :]
    return _parse_directed_int(value)


def _parse_directed_phys(raw: str) -> int:
    value = raw.strip().lower()
    if value.startswith("phys="):
        value = value.split("=", 1)[1]
    if value.startswith(("r", "f")):
        value = value[1:]
    return _parse_directed_int(value)


def _parse_directed_force_phys(
    raw: str,
    *,
    default_class_id: int = 0,
) -> tuple[dict[int, int], int]:
    """Parse a directed force-phys proof vector for one register class.

    Supported entries:
      - ``0:58:4`` (class_id:ig_idx:phys)
      - ``58:4`` (uses --directed-class/default_class_id)
      - ``class0:ig58:phys=r4`` (force-vector style)
    """
    groups = _parse_directed_force_phys_groups(
        raw,
        default_class_id=default_class_id,
    )
    if len(groups) > 1:
        class_ids = sorted(groups)
        raise ValueError(
            "--directed-force-phys currently supports one register "
            f"class per run; saw class {class_ids[0]} and {class_ids[1]}"
        )
    class_id, force_phys = next(iter(groups.items()))
    return force_phys, class_id


def _parse_directed_force_phys_groups(
    raw: str,
    *,
    default_class_id: int = 0,
) -> dict[int, dict[int, int]]:
    """Parse a directed force-phys proof vector grouped by register class."""
    groups: dict[int, dict[int, int]] = {}
    for entry in raw.split(","):
        spec = entry.strip()
        if not spec:
            continue
        parts = [part.strip() for part in spec.split(":")]
        try:
            if len(parts) == 3 and parts[0].lower().startswith("class"):
                entry_class = _parse_directed_class(parts[0])
                ig_idx = _parse_directed_int(parts[1], prefix="ig")
                phys = _parse_directed_phys(parts[2])
            elif len(parts) == 3:
                entry_class = _parse_directed_class(parts[0])
                ig_idx = _parse_directed_int(parts[1], prefix="ig")
                phys = _parse_directed_phys(parts[2])
            elif len(parts) == 2:
                entry_class = default_class_id
                ig_idx = _parse_directed_int(parts[0], prefix="ig")
                phys = _parse_directed_phys(parts[1])
            else:
                raise ValueError(
                    "expected class_id:ig_idx:phys, ig_idx:phys, or class0:ig58:phys=r4"
                )
        except ValueError as exc:
            raise ValueError(
                f"invalid --directed-force-phys entry {spec!r}: {exc}"
            ) from exc
        groups.setdefault(entry_class, {})[ig_idx] = phys
    if not groups:
        raise ValueError("--directed-force-phys did not contain any entries")
    return dict(sorted(groups.items()))


def _format_directed_force_phys(force_phys: dict[int, int], class_id: int) -> str:
    return ",".join(
        f"{class_id}:{ig_idx}:{phys}" for ig_idx, phys in sorted(force_phys.items())
    )


def _format_directed_force_phys_groups(groups: dict[int, dict[int, int]]) -> str:
    return ",".join(
        f"{class_id}:{ig_idx}:{phys}"
        for class_id, force_phys in sorted(groups.items())
        for ig_idx, phys in sorted(force_phys.items())
    )


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _parse_triage_candidate(raw: str) -> tuple[str, Path]:
    if "=" in raw:
        candidate_id, path_s = raw.split("=", 1)
        candidate_id = candidate_id.strip()
        path = Path(path_s.strip())
    else:
        path = Path(raw.strip())
        candidate_id = path.stem
    if not candidate_id:
        raise typer.BadParameter(f"candidate spec {raw!r} has an empty candidate id")
    if not path.is_file():
        raise typer.BadParameter(f"candidate source not found: {path}")
    return candidate_id, path


def _load_triage_telemetry(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        telemetry = payload.get("directed_telemetry", [])
    else:
        telemetry = payload
    if not isinstance(telemetry, list):
        raise typer.BadParameter(
            "--telemetry must contain a JSON list or a directed_telemetry list"
        )
    return [dict(entry) for entry in telemetry if isinstance(entry, dict)]


def _triage_telemetry_for(
    telemetry: list[dict],
    *,
    candidate_id: str,
    source_hash: str,
) -> dict | None:
    for entry in telemetry:
        if entry.get("candidate_id") == candidate_id:
            return entry
    for entry in telemetry:
        if entry.get("source_hash") == source_hash:
            return entry
    return None


def _format_assignment(entry: dict, *, status: str) -> str:
    original = entry.get("original_ig")
    desired = entry.get("desired_phys")
    assigned = entry.get("assigned_phys")
    if status == "satisfied":
        return f"ig{original}->r{desired}"
    if status == "blocked":
        return f"ig{original}: wanted r{desired}, got r{assigned}"
    reason = entry.get("reason")
    suffix = f" ({reason})" if reason else ""
    return f"ig{original}: wanted r{desired}, abstained{suffix}"


def _transform_plan_payload(
    plan,
    probes,
    *,
    write_dir: Path | None = None,
    family_diagnostics=(),
    source_resolution: dict | None = None,
) -> dict:
    probe_payloads: list[dict] = []
    if write_dir is not None:
        write_dir.mkdir(parents=True, exist_ok=True)
    for probe in probes:
        item = asdict(probe)
        candidate_path = None
        if write_dir is not None:
            candidate_path = write_dir / f"{probe.probe_id.replace('/', '_')}.c"
            candidate_path.write_text(probe.candidate_text)
        item["candidate_path"] = None if candidate_path is None else str(candidate_path)
        item.pop("candidate_text", None)
        probe_payloads.append(item)
    return {
        "plan": asdict(plan),
        "probes": probe_payloads,
        "family_diagnostics": [asdict(item) for item in family_diagnostics],
        "source_resolution": source_resolution or {},
    }


def _load_node_set_delta(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read --node-set-delta {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse --node-set-delta {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--node-set-delta must contain a JSON object")
    return payload


RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID = (
    "retained_gpr_case_c_window_order_continuation"
)
RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID = (
    "retained_gpr_case_c_post_source_owner_backtrack"
)
RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID = (
    "retained_gpr_case_c_target_live_range_repair"
)
RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID = (
    "retained_fpr_case_c_target_live_range_repair"
)
RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID = (
    "retained_case_c_alternate_source_owner_discovery"
)
RETAINED_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_IDS = frozenset(
    {
        RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
        RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
        RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID,
    }
)
RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID = (
    "retained_gpr_case_c_simplify_order_continuation"
)
RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID = (
    "retained_gpr_common_subexpr_coalesce_source"
)
PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID = (
    "pcode_only_gpr_bool_mask_temp_repair"
)


def _load_select_order_window_order_context(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read --select-order-json {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse --select-order-json {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--select-order-json must contain a JSON object")
    fallback = payload.get("window_order_fallback")
    fallback_leads = (
        fallback.get("leads")
        if isinstance(fallback, dict) and isinstance(fallback.get("leads"), list)
        else []
    )
    source_attributions = payload.get("window_order_source_attributions")
    if not isinstance(source_attributions, dict):
        source_attributions = {}
    probe_diagnostics = payload.get("window_order_probe_diagnostics")
    repair_goals = payload.get("retained_case_c_repair_goals")
    if not isinstance(repair_goals, list):
        repair_goals = []
    simplify_order_goals = payload.get("retained_case_c_simplify_order_goals")
    if not isinstance(simplify_order_goals, list):
        simplify_order_goals = []
    lower_drift_residual = payload.get("retained_case_c_lower_drift_residual")
    return {
        "payload_path": str(path),
        "fallback_leads": fallback_leads,
        "source_attributions": source_attributions,
        "retained_case_c_repair_goals": [
            goal for goal in repair_goals if isinstance(goal, dict)
        ],
        "retained_case_c_simplify_order_goals": [
            goal for goal in simplify_order_goals if isinstance(goal, dict)
        ],
        "retained_case_c_lower_drift_residual": lower_drift_residual,
        "probe_diagnostics": (
            probe_diagnostics if isinstance(probe_diagnostics, dict) else None
        ),
        "diagnostics": {
            key: payload.get(key)
            for key in (
                "source",
                "baseline_pcdump_path",
                "target_orders",
                "class_id",
            )
            if key in payload
        },
    }


def _normalize_current_owner_span(
    span: dict,
    *,
    protected_targets: dict | None,
    attempted_targets: dict | None,
    force_phys_targets: dict | None,
) -> dict:
    normalized = dict(span)
    if protected_targets and not isinstance(
        normalized.get("protected_targets"),
        dict,
    ):
        normalized["protected_targets"] = dict(protected_targets)
    if attempted_targets and not isinstance(
        normalized.get("attempted_targets"),
        dict,
    ):
        normalized["attempted_targets"] = dict(attempted_targets)
    if force_phys_targets and not isinstance(
        normalized.get("force_phys_targets"),
        dict,
    ):
        normalized["force_phys_targets"] = dict(force_phys_targets)
    return normalized


def _collect_current_owner_spans_from_summary(summary: object) -> list[dict]:
    if not isinstance(summary, dict):
        return []
    protected_targets = (
        summary.get("protected_targets")
        if isinstance(summary.get("protected_targets"), dict)
        else None
    )
    attempted_targets = (
        summary.get("attempted_targets")
        if isinstance(summary.get("attempted_targets"), dict)
        else None
    )
    force_phys_targets = {}
    force_phys_targets.update(attempted_targets or {})
    force_phys_targets.update(protected_targets or {})
    spans: list[dict] = []
    for raw_span in summary.get("source_owner_terminal_spans", []) or []:
        if not isinstance(raw_span, dict):
            continue
        spans.append(
            _normalize_current_owner_span(
                raw_span,
                protected_targets=protected_targets,
                attempted_targets=attempted_targets,
                force_phys_targets=force_phys_targets,
            )
        )
    return spans


def _stack_symbol_from_first_def(first_def: object) -> str | None:
    if not isinstance(first_def, dict):
        return None
    operands = first_def.get("operands")
    if not isinstance(operands, str):
        return None
    marker = "(r1)"
    end = operands.find(marker)
    if end < 0:
        return None
    comma = operands.rfind(",", 0, end)
    if comma < 0:
        return None
    symbol = operands[comma + 1 : end].strip()
    return symbol or None


def _current_owner_span_from_unsupported(span: dict) -> dict | None:
    kind = span.get("kind")
    if kind == "target-live-range-source-owner-terminal":
        return dict(span)
    if kind not in {
        "blocker-chain-source-owner",
        "blocker-chain-operand-source-owner",
    }:
        return None
    source_expression = span.get("source_expression")
    if not isinstance(source_expression, str) or not source_expression.strip():
        return None
    first_def = span.get("first_def")
    payload = {
        "kind": "target-live-range-source-owner-terminal",
        "family_id": RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
        "target_ig": span.get("target_ig"),
        "target_phys": span.get("target_phys"),
        "interferer_ig": span.get("operand_virtual") or span.get("blocker_ig"),
        "interferer_phys": (
            span.get("operand_assigned_reg") or span.get("blocker_phys")
        ),
        "source_expression": source_expression.strip(),
        "source_type": "int",
        "source_owner_kind": span.get("source_kind"),
        "source_owner_confidence": span.get("confidence"),
        "source_owner_first_def": first_def,
        "stack_symbol": _stack_symbol_from_first_def(first_def),
        "operand_index": span.get("operand_index"),
        "operand_virtual": span.get("operand_virtual"),
        "operand_assigned_reg": span.get("operand_assigned_reg"),
        "status": "materialized",
        "source_owner_status": "current-source-owner-probes-exhausted",
        "next_source_owner_status": "not-discovered",
    }
    return {key: value for key, value in payload.items() if value not in (None, [], {})}


def _load_current_owner_exhaustion_context(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read --current-owner-exhaustion-json {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse --current-owner-exhaustion-json {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(
            "--current-owner-exhaustion-json must contain a JSON object"
        )
    spans: list[dict] = []
    spans.extend(
        _collect_current_owner_spans_from_summary(
            payload.get("retained_case_c_target_live_range_repair_summary")
        )
    )
    validation_summary = payload.get("validation_summary")
    if isinstance(validation_summary, dict):
        spans.extend(
            _collect_current_owner_spans_from_summary(
                validation_summary.get(
                    "retained_case_c_target_live_range_repair_summary"
                )
            )
        )
    residual = payload.get("residual_case_c_source_repair")
    unsupported_source_owner_spans: list[dict] = []
    if isinstance(residual, dict):
        target_live_range = residual.get("target_live_range_repair_exhaustion")
        if isinstance(target_live_range, dict):
            spans.extend(_collect_current_owner_spans_from_summary(target_live_range))
            for raw_span in (
                target_live_range.get("unsupported_source_owner_spans", []) or []
            ):
                if isinstance(raw_span, dict):
                    unsupported_source_owner_spans.append(dict(raw_span))
                    converted = _current_owner_span_from_unsupported(raw_span)
                    if converted is not None:
                        spans.append(converted)
        for raw_span in residual.get("unsupported_source_owner_spans", []) or []:
            if isinstance(raw_span, dict):
                unsupported_source_owner_spans.append(dict(raw_span))
                converted = _current_owner_span_from_unsupported(raw_span)
                if converted is not None:
                    spans.append(converted)
    for raw_span in payload.get("unsupported_source_owner_spans", []) or []:
        if isinstance(raw_span, dict):
            unsupported_source_owner_spans.append(dict(raw_span))
            converted = _current_owner_span_from_unsupported(raw_span)
            if converted is not None:
                spans.append(converted)

    by_key: dict[tuple, dict] = {}
    for span in spans:
        key = (
            span.get("family_id"),
            span.get("target_ig"),
            span.get("target_phys"),
            span.get("interferer_ig"),
            span.get("interferer_phys"),
            span.get("source_expression"),
        )
        by_key[key] = span
    return {
        "payload_path": str(path),
        "source_owner_terminal_spans": list(by_key.values()),
        "unsupported_source_owner_spans": unsupported_source_owner_spans,
        "source_attributions": (
            payload.get("window_order_source_attributions")
            if isinstance(payload.get("window_order_source_attributions"), dict)
            else {}
        ),
    }


def _load_coalesce_suggest_context(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read --coalesce-suggest-json {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse --coalesce-suggest-json {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--coalesce-suggest-json must contain a JSON object")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list):
        raise typer.BadParameter(
            "--coalesce-suggest-json must contain a top-level pairs array"
        )
    result = dict(payload)
    result["payload_path"] = str(path)
    return result


def _load_virtual_explain_context(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(
            f"could not read --virtual-explain-json {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"could not parse --virtual-explain-json {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--virtual-explain-json must contain a JSON object")
    if not isinstance(payload.get("virtuals"), list):
        raise typer.BadParameter(
            "--virtual-explain-json must contain a top-level virtuals array"
        )
    result = dict(payload)
    result["payload_path"] = str(path)
    return result


def _node_set_delta_target_ig(entry: dict) -> int | None:
    try:
        return int(entry.get("target_ig"))
    except (TypeError, ValueError):
        return None


def _append_unique_node_set_delta_entry(
    items: list[dict],
    seen_targets: set[int],
    entry: dict,
) -> None:
    target_ig = _node_set_delta_target_ig(entry)
    if target_ig is not None:
        if target_ig in seen_targets:
            return
        seen_targets.add(target_ig)
    elif entry in items:
        return
    items.append(entry)


def _node_set_delta_classification_source_text(
    *,
    delta: dict,
    source_text: str | None,
    function: str | None,
) -> str | None:
    if source_text is None:
        return None
    target_function = str(delta.get("function") or function or "")
    if not target_function:
        return None
    from src.mwcc_debug.source_patch import find_function

    if find_function(source_text, target_function) is None:
        return None
    return source_text


def _node_set_delta_summary(
    payload: dict | None,
    probes,
    *,
    source_text: str | None = None,
    function: str | None = None,
) -> dict | None:
    if payload is None:
        return None

    nested = payload.get("node_set_delta")
    delta = dict(nested if isinstance(nested, dict) else payload)
    if function and not delta.get("function"):
        delta["function"] = function
    missing = delta.get("missing_virtuals")
    missing_entries = (
        [entry for entry in missing if isinstance(entry, dict)]
        if isinstance(missing, list)
        else []
    )
    node_set_probes = [
        probe
        for probe in probes
        if str(getattr(probe, "mutator_key", "")).startswith("steer_node_set_delta")
    ]

    skipped: list[dict] = []
    capped: list[dict] = []
    skipped_targets: set[int] = set()
    capped_entry_targets: set[int] = set()
    materialized_targets: set[int] = set()
    for probe in node_set_probes:
        meta = getattr(probe, "payload", {}).get("node_set_delta")
        if not isinstance(meta, dict):
            continue
        for request in meta.get("requests") or []:
            if not isinstance(request, dict):
                continue
            target_ig = _node_set_delta_target_ig(request)
            if target_ig is not None:
                materialized_targets.add(target_ig)
        for entry in meta.get("skipped_missing_virtuals") or []:
            if isinstance(entry, dict):
                _append_unique_node_set_delta_entry(
                    skipped,
                    skipped_targets,
                    entry,
                )
        for entry in meta.get("capped_missing_virtuals") or []:
            if isinstance(entry, dict):
                _append_unique_node_set_delta_entry(
                    capped,
                    capped_entry_targets,
                    entry,
                )

    classification_source_text = _node_set_delta_classification_source_text(
        delta=delta,
        source_text=source_text,
        function=function,
    )
    from src.mwcc_debug.node_set_split import (
        is_node_set_request_introducible,
        request_from_node_set_delta,
    )

    bindable_entries: list[dict] = []
    introducible_entries: list[dict] = []
    materializable_entries: list[dict] = []
    for entry in missing_entries:
        target_ig = _node_set_delta_target_ig(entry)
        if target_ig is None:
            continue
        entry_delta = dict(delta)
        entry_delta["missing_virtuals"] = [entry]
        request = request_from_node_set_delta(
            entry_delta,
            target_ig=target_ig,
            source_text=classification_source_text,
        )
        if request is None:
            continue
        if request.var_name is not None and request.blocked_reason is None:
            bindable_entries.append(entry)
            materializable_entries.append(entry)
            continue
        if is_node_set_request_introducible(request):
            introducible_entries.append(entry)
            materializable_entries.append(entry)
            continue
        if request.var_name is None or request.blocked_reason is not None:
            blocked = dict(entry)
            if request.blocked_reason is not None:
                blocked["blocked_reason"] = request.blocked_reason
            _append_unique_node_set_delta_entry(
                skipped,
                skipped_targets,
                blocked,
            )
            continue

    omitted: list[dict] = []
    omitted_targets: set[int] = set()
    for entry in materializable_entries:
        target_ig = _node_set_delta_target_ig(entry)
        if target_ig is None:
            continue
        if target_ig in materialized_targets or target_ig in capped_entry_targets:
            continue
        _append_unique_node_set_delta_entry(
            omitted,
            omitted_targets,
            dict(entry, omitted_reason="no node-set probe materialized"),
        )

    summary = {
        "provided": True,
        "missing_count": len(missing_entries),
        "bindable_count": len(bindable_entries),
        "introducible_count": len(introducible_entries),
        "skipped_count": len(skipped),
        "skipped_missing_virtuals": skipped,
        "omitted_count": len(omitted),
        "omitted_missing_virtuals": omitted,
    }
    if capped:
        summary["capped_count"] = len(capped)
        summary["capped_missing_virtuals"] = capped
    return summary


def _node_set_delta_planning_summary(
    summary: dict | None,
    probes,
    *,
    max_per_family: int,
) -> dict | None:
    if summary is None:
        return None
    node_set_probe_count = sum(
        1
        for probe in probes
        if str(getattr(probe, "mutator_key", "")).startswith("steer_node_set_delta")
    )
    if node_set_probe_count >= max_per_family:
        stop_condition = "node-set-delta-budget-filled"
    elif summary.get("omitted_count"):
        stop_condition = "node-set-delta-omitted-targets"
    elif summary.get("skipped_count") and not node_set_probe_count:
        stop_condition = "node-set-delta-all-blocked"
    elif node_set_probe_count:
        stop_condition = "node-set-delta-exhausted"
    else:
        stop_condition = "node-set-delta-no-probes"
    return {
        "stop_condition": stop_condition,
        "node_set_probe_count": node_set_probe_count,
        "max_per_family": max_per_family,
    }


def _record_transform_plan_attempt(
    *,
    function: str,
    plan,
    probes,
    source_path: Path | None,
    validation_results: list[dict] | None = None,
) -> dict:
    from src.cli.tracking import record_attempt

    clusters = ",".join(cluster.cluster_id for cluster in plan.clusters)
    family_ids = ",".join(family.family_id for family in plan.families)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("outcome") == "retained-source-improvement"
    ]
    negative_results = [
        result
        for result in (validation_results or [])
        if result.get("outcome") == "negative-evidence"
    ]
    refactor_results = [
        result
        for result in (validation_results or [])
        if result.get("outcome") == "larger-refactor-recommended"
    ]
    match_values = [
        float(result["match_percent"])
        for result in (validation_results or [])
        if result.get("match_percent") is not None
    ]
    match_percent = max(match_values) if match_values else 0.0
    movement_note = _validation_movement_note(validation_results or [])
    refactor_note = _validation_refactor_note(refactor_results)
    if retained_results:
        outcome = "improved"
        retained = True
        blocker = ""
        retained_ids = ",".join(
            str(result.get("probe_id")) for result in retained_results
        )
        note = (
            f"transform-plan validation retained-source-improvement "
            f"probes={retained_ids} clusters={clusters} families={family_ids}"
        )
        if movement_note:
            note += f" {movement_note}"
    elif refactor_results:
        outcome = "blocked"
        retained = False
        blocker = "transform-plan validation recommends larger refactor"
        note = (
            f"transform-plan larger-refactor clusters={clusters} families={family_ids}"
        )
        if refactor_note:
            note += f" {refactor_note}"
    elif validation_results and negative_results:
        outcome = "blocked"
        retained = False
        blocker = "transform-plan validation exhausted probes with negative evidence"
        note = f"transform-plan negative-evidence probes={len(negative_results)} clusters={clusters} families={family_ids}"
        if movement_note:
            note += f" {movement_note}"
    elif probes:
        outcome = "neutral"
        retained = False
        blocker = ""
        note = f"transform-plan probes={len(probes)} clusters={clusters} families={family_ids}"
    else:
        outcome = "blocked"
        retained = False
        blocker = (
            "transform-plan produced no materialized probes; target function "
            "body is absent or no applicable anchors matched"
        )
        note = f"transform-plan no-probes clusters={clusters} families={family_ids}"
    summary = record_attempt(
        function,
        match_percent=match_percent,
        outcome=outcome,
        classification="transform-corpus",
        blocker=blocker,
        note=note,
        retained=retained,
        source_file=str(source_path) if source_path is not None else "",
    )
    attempts = summary.get("attempts", [])
    attempt = attempts[-1] if attempts else {}
    return {
        "outcome": outcome,
        "attempt_index": attempt.get("index"),
        "classification": "transform-corpus",
        "blocker": blocker,
        "note": note,
        "retained": retained,
        "match_percent": match_percent,
    }


def _parse_validation_payload(stdout: str) -> dict | None:
    text = stdout.strip()
    if not text:
        return None
    candidates = [text, *reversed(text.splitlines())]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _payload_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "matched"}:
            return True
        if lowered in {"0", "false", "no", "mismatch", "unmatched"}:
            return False
    return None


def _payload_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed > 100:
        return None
    return parsed


def _validation_payload_is_unscoreable(payload: dict) -> bool:
    if not payload.get("error"):
        return False
    if isinstance(payload.get("target_score"), dict):
        return False
    if isinstance(payload.get("expression_score"), dict):
        return False
    for key in ("match", "matched"):
        if payload.get(key) is not None:
            return False
    return True


def _classify_validation_result(
    returncode: int,
    stdout: str,
    stderr: str,
    payload: dict | None = None,
) -> str:
    if payload:
        if _validation_payload_is_unscoreable(payload):
            return "blocked"
        outcome = str(payload.get("outcome") or payload.get("status") or "").lower()
        if outcome in {
            "retained",
            "retained-source-improvement",
            "improved",
            "matched",
        }:
            return "retained-source-improvement"
        if outcome in {"larger-refactor", "larger_refactor", "refactor"}:
            return "larger-refactor-recommended"
        if outcome in {"negative", "negative-evidence", "no-improvement", "failed"}:
            return "negative-evidence"
        match_value = _payload_bool(payload.get("match", payload.get("matched")))
        if match_value is True:
            return "retained-source-improvement"
        if match_value is False and returncode == 0:
            return "negative-evidence"
    text = f"{stdout}\n{stderr}".lower()
    if returncode == 0 and any(
        marker in text
        for marker in (
            "match=true",
            "matched=true",
            "retained-source-improvement",
            "fix found",
        )
    ):
        return "retained-source-improvement"
    if returncode == 0:
        return "negative-evidence"
    return "blocked"


def _validation_movement_note(results: list[dict]) -> str:
    movement_items: list[str] = []
    for result in results:
        movement = result.get("target_assignment_movement")
        if isinstance(movement, dict):
            for key, value in sorted(movement.items()):
                movement_items.append(f"{key}:{value}")
        elif isinstance(movement, list):
            movement_items.extend(str(item) for item in movement)
        elif movement:
            movement_items.append(str(movement))
    if not movement_items:
        return ""
    return "movement=" + ",".join(movement_items[:8])


def _validation_refactor_note(results: list[dict]) -> str:
    regions: list[str] = []
    uncovered: list[str] = []
    for result in results:
        source_regions = result.get("source_regions")
        if isinstance(source_regions, list):
            regions.extend(str(item) for item in source_regions)
        elif source_regions:
            regions.append(str(source_regions))
        classes = result.get("uncovered_transform_classes")
        if isinstance(classes, list):
            uncovered.extend(str(item) for item in classes)
        elif classes:
            uncovered.append(str(classes))
    parts = []
    if regions:
        parts.append("source_regions=" + ",".join(regions[:6]))
    if uncovered:
        parts.append("uncovered=" + ",".join(uncovered[:6]))
    return " ".join(parts)


def _run_transform_validations(
    probe_payloads: list[dict],
    *,
    validate_command: str,
    stop_on_retained: bool = False,
) -> list[dict]:
    results: list[dict] = []
    for probe in probe_payloads:
        candidate_path = probe.get("candidate_path")
        if not candidate_path:
            results.append(
                {
                    "probe_id": probe.get("probe_id"),
                    "family_id": probe.get("family_id"),
                    "outcome": "blocked",
                    "returncode": None,
                    "command": None,
                    "stdout": "",
                    "stderr": "candidate_path missing; pass --write-probes",
                }
            )
            continue
        args = [
            token.replace("{candidate_path}", str(candidate_path)).replace(
                "{candidate}", str(candidate_path)
            )
            for token in shlex.split(validate_command)
        ]
        proc = subprocess.run(args, capture_output=True, text=True)
        validation_payload = _parse_validation_payload(proc.stdout)
        outcome = _classify_validation_result(
            proc.returncode,
            proc.stdout,
            proc.stderr,
            validation_payload,
        )
        match_percent = None
        target_assignment_movement = None
        recommendation = None
        source_regions = None
        uncovered_transform_classes = None
        target_score = None
        expression_score = None
        structural_guard = None
        structural_guard_error = None
        if validation_payload:
            match_percent = _payload_float(
                validation_payload.get(
                    "match_percent",
                    validation_payload.get("fuzzy_match_percent"),
                )
            )
            target_assignment_movement = validation_payload.get(
                "target_assignment_movement",
                validation_payload.get(
                    "assignment_movement",
                    validation_payload.get("movement"),
                ),
            )
            recommendation = validation_payload.get("recommendation")
            source_regions = validation_payload.get("source_regions")
            uncovered_transform_classes = validation_payload.get(
                "uncovered_transform_classes"
            )
            target_score = validation_payload.get("target_score")
            expression_score = validation_payload.get("expression_score")
            structural_guard = validation_payload.get("structural_guard")
            structural_guard_error = validation_payload.get("structural_guard_error")
        result = {
            "probe_id": probe.get("probe_id"),
            "family_id": probe.get("family_id"),
            "outcome": outcome,
            "returncode": proc.returncode,
            "command": args,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "validator_payload": validation_payload,
            "match_percent": match_percent,
            "target_assignment_movement": target_assignment_movement,
            "recommendation": recommendation,
            "source_regions": source_regions,
            "uncovered_transform_classes": uncovered_transform_classes,
            "target_score": target_score,
            "expression_score": expression_score,
            "structural_guard": structural_guard,
            "structural_guard_error": structural_guard_error,
        }
        result["evidence"] = _transform_validation_evidence(
            probe,
            result,
        )
        retained_window_classification = (
            _classify_retained_case_c_window_order_validation(probe, result)
        )
        retained_post_source_owner_classification = (
            _classify_retained_case_c_post_source_owner_backtrack_validation(
                probe,
                result,
            )
        )
        retained_target_live_range_classification = (
            _classify_retained_case_c_target_live_range_validation(probe, result)
        )
        retained_simplify_order_classification = (
            _classify_retained_case_c_simplify_order_validation(probe, result)
        )
        if retained_window_classification is not None:
            result["retained_case_c_window_order_classification"] = (
                retained_window_classification
            )
            if isinstance(result.get("evidence"), dict):
                result["evidence"]["retained_case_c_window_order_classification"] = (
                    retained_window_classification
                )
        if retained_post_source_owner_classification is not None:
            result["retained_case_c_post_source_owner_backtrack_classification"] = (
                retained_post_source_owner_classification
            )
            if isinstance(result.get("evidence"), dict):
                result["evidence"][
                    "retained_case_c_post_source_owner_backtrack_classification"
                ] = retained_post_source_owner_classification
        if retained_target_live_range_classification is not None:
            result["retained_case_c_target_live_range_classification"] = (
                retained_target_live_range_classification
            )
            if isinstance(result.get("evidence"), dict):
                result["evidence"][
                    "retained_case_c_target_live_range_classification"
                ] = retained_target_live_range_classification
        if retained_simplify_order_classification is not None:
            result["retained_case_c_simplify_order_classification"] = (
                retained_simplify_order_classification
            )
            if isinstance(result.get("evidence"), dict):
                result["evidence"]["retained_case_c_simplify_order_classification"] = (
                    retained_simplify_order_classification
                )
        results.append(result)
        if (
            (
                retained_window_classification is not None
                and retained_window_classification.get("classification") == "exact"
            )
            or (
                retained_post_source_owner_classification is not None
                and retained_post_source_owner_classification.get("classification")
                == "exact"
            )
            or (
                retained_target_live_range_classification is not None
                and retained_target_live_range_classification.get("classification")
                == "exact"
            )
            or (
                retained_simplify_order_classification is not None
                and retained_simplify_order_classification.get("classification")
                == "exact"
            )
        ):
            break
        if stop_on_retained and outcome == "retained-source-improvement":
            break
    return results


def _transform_validation_evidence(probe: dict, result: dict) -> dict:
    evidence = {
        "probe_id": result.get("probe_id"),
        "family_id": result.get("family_id"),
        "family_label": probe.get("family_label"),
        "outcome": result.get("outcome"),
        "semantic_risk": probe.get("semantic_risk"),
        "source_region": probe.get("source_region"),
        "target_assignments": list(probe.get("target_assignments") or []),
        "expected_compiler_effect": probe.get("expected_compiler_effect"),
        "match_percent": result.get("match_percent"),
        "target_assignment_movement": result.get("target_assignment_movement"),
        "recommendation": result.get("recommendation"),
        "source_regions": result.get("source_regions"),
        "uncovered_transform_classes": result.get("uncovered_transform_classes"),
    }
    payload = result.get("validator_payload")
    target_score = payload.get("target_score") if isinstance(payload, dict) else None
    if isinstance(target_score, dict):
        evidence["target_score"] = target_score
    first_divergence = (
        payload.get("first_divergence") if isinstance(payload, dict) else None
    )
    if isinstance(first_divergence, dict):
        evidence["first_divergence"] = first_divergence
    first_divergence_movement = (
        payload.get("first_divergence_movement") if isinstance(payload, dict) else None
    )
    if isinstance(first_divergence_movement, dict):
        evidence["first_divergence_movement"] = first_divergence_movement
    expression_score = (
        payload.get("expression_score") if isinstance(payload, dict) else None
    )
    if isinstance(expression_score, dict):
        evidence["expression_score"] = expression_score
        false_positive_count = _validation_numeric(
            expression_score.get("false_positive_virtual_id_hit_count")
        )
        if false_positive_count is not None:
            evidence["false_positive_virtual_id_hit_count"] = int(false_positive_count)
    elif isinstance(payload, dict):
        false_positive_count = _validation_numeric(
            payload.get("false_positive_virtual_id_hit_count")
        )
        if false_positive_count is not None:
            evidence["false_positive_virtual_id_hit_count"] = int(false_positive_count)
    structural_guard = (
        payload.get("structural_guard") if isinstance(payload, dict) else None
    )
    if isinstance(structural_guard, dict):
        evidence["structural_guard"] = structural_guard
    structural_guard_error = (
        payload.get("structural_guard_error") if isinstance(payload, dict) else None
    )
    if structural_guard_error is not None:
        evidence["structural_guard_error"] = structural_guard_error
    return evidence


def _stack_array_node_set_terminal_proof(
    probe_payloads: list[dict],
    validation_results: list[dict],
) -> dict | None:
    result_by_probe = {
        str(result.get("probe_id")): result
        for result in validation_results
        if result.get("probe_id") is not None
    }
    target_registers: dict[str, str] = {}
    blocked_sources: list[dict] = []
    candidates: list[dict] = []
    stack_probe_count = 0

    for probe in probe_payloads:
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        node_set = (
            payload.get("node_set_delta")
            if isinstance(payload.get("node_set_delta"), dict)
            else {}
        )
        requests = [
            item for item in (node_set.get("requests") or [])
            if isinstance(item, dict)
        ]
        if not any(
            item.get("source_kind") == "stack-array-base"
            for item in requests
        ):
            continue
        stack_probe_count += 1
        skipped = [
            item for item in (node_set.get("skipped_missing_virtuals") or [])
            if isinstance(item, dict)
        ]
        capped = [
            item for item in (node_set.get("capped_missing_virtuals") or [])
            if isinstance(item, dict)
        ]
        for item in [*requests, *skipped, *capped]:
            ig = _node_set_delta_target_ig(item)
            target_reg = _node_set_entry_target_register(item)
            if ig is not None and target_reg is not None:
                target_registers.setdefault(str(ig), target_reg)
        for item in [*skipped, *capped]:
            ig = _node_set_delta_target_ig(item)
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            blocked_sources.append({
                "target_ig": ig,
                "target_reg": _node_set_entry_target_register(item),
                "source_expression": source.get("expression"),
                "source_kind": source.get("kind"),
                "blocked_reason": item.get("blocked_reason"),
            })

        probe_id = probe.get("probe_id")
        result = result_by_probe.get(str(probe_id))
        if result is None:
            continue
        validator_payload = (
            result.get("validator_payload")
            if isinstance(result.get("validator_payload"), dict)
            else {}
        )
        target_score = _validation_payload_dict(result, "target_score")
        source_hunks = payload.get("source_hunks")
        if not source_hunks and node_set.get("hunk"):
            source_hunks = [{
                "hunk_id": node_set.get("patch_candidate_id") or probe_id,
                "unified_diff": node_set.get("hunk"),
            }]
        candidates.append({
            "probe_id": probe_id,
            "family_id": probe.get("family_id"),
            "outcome": result.get("outcome"),
            "candidate_path": probe.get("candidate_path"),
            "source_retained": validator_payload.get(
                "source_retained",
                probe.get("candidate_path"),
            ),
            "pcdump_path": validator_payload.get("pcdump_path"),
            "target_score": target_score,
            "assigned_registers": _target_score_assigned_registers(
                target_score,
                target_registers,
            ),
            "source_hunks": source_hunks,
        })

    if stack_probe_count == 0 or not candidates:
        return None
    if not all(
        _target_score_covers_targets(
            candidate.get("target_score"),
            target_registers,
        )
        for candidate in candidates
    ):
        return None
    if any(
        _target_score_hits_all_targets(
            candidate.get("target_score"),
            target_registers,
        )
        for candidate in candidates
    ):
        return None
    next_handoff = (
        "Inspect the retained pcdump/source for the stack-array base binding, "
        "then add source ownership for any skipped load/store-address base "
        "virtuals before retrying the coupled node-set targets."
    )
    if blocked_sources:
        unresolved = ", ".join(
            f"ig{entry['target_ig']} {entry.get('source_expression')}"
            for entry in blocked_sources[:4]
        )
        next_handoff = (
            "Skipped load/store-address targets still lack a source owner "
            f"({unresolved}); inspect those pcode base virtual producers and "
            "link them to the stack array before retrying the coupled targets."
        )
    return {
        "terminal_reason": "stack-array-base-targets-not-realized",
        "source_family": "stack-array-base",
        "target_registers": target_registers,
        "generated_count": stack_probe_count,
        "evaluated_count": len(candidates),
        "blocked_sources": blocked_sources,
        "candidates": candidates,
        "next_handoff": next_handoff,
    }


def _node_set_entry_target_register(entry: dict) -> str | None:
    for key in ("target_reg", "target_register", "current_register"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            if key == "current_register":
                continue
            return value
    for key in ("target_regs", "desired_registers"):
        values = entry.get(key)
        if isinstance(values, (list, tuple)) and values:
            value = values[0]
            if isinstance(value, str):
                return value
            if isinstance(value, int):
                return f"r{value}"
    return None


def _target_score_assigned_registers(
    target_score: dict | None,
    target_registers: dict[str, str],
) -> dict[str, str | int | None]:
    virtuals = target_score.get("virtuals") if isinstance(target_score, dict) else None
    assigned: dict[str, str | int | None] = {}
    for ig in target_registers:
        actual = None
        if isinstance(virtuals, dict):
            entry = virtuals.get(str(ig))
            if isinstance(entry, dict):
                actual = entry.get("actual")
        assigned[str(ig)] = f"r{actual}" if isinstance(actual, int) else actual
    return assigned


def _target_score_covers_targets(
    target_score: dict | None,
    target_registers: dict[str, str],
) -> bool:
    if not target_registers:
        return False
    virtuals = target_score.get("virtuals") if isinstance(target_score, dict) else None
    if not isinstance(virtuals, dict):
        return False
    return all(str(ig) in virtuals for ig in target_registers)


def _target_score_hits_all_targets(
    target_score: dict | None,
    target_registers: dict[str, str],
) -> bool:
    if not target_registers:
        return False
    virtuals = target_score.get("virtuals") if isinstance(target_score, dict) else None
    if not isinstance(virtuals, dict):
        return False
    for ig, target_reg in target_registers.items():
        entry = virtuals.get(str(ig))
        if not isinstance(entry, dict):
            return False
        matched = entry.get("matched", entry.get("hit"))
        if isinstance(matched, bool):
            if not matched:
                return False
            continue
        actual = entry.get("actual")
        try:
            if int(str(target_reg).lstrip("rf")) != int(actual):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _probe_target_mapping(
    probe: dict,
    key: str,
) -> dict[str, int]:
    payload = probe.get("payload")
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for raw_ig, raw_phys in value.items():
        try:
            out[str(int(raw_ig))] = int(raw_phys)
        except (TypeError, ValueError):
            continue
    return out


def _virtual_entry_hit(
    target_score: dict | None,
    ig: str,
    expected: int,
) -> bool:
    if not isinstance(target_score, dict):
        return False
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, dict):
        return False
    entry = virtuals.get(ig)
    if not isinstance(entry, dict):
        return False
    for key in ("matched", "hit"):
        value = entry.get(key)
        if isinstance(value, bool):
            return value
        parsed = _payload_bool(value)
        if parsed is not None:
            return parsed
    actual = entry.get("actual")
    try:
        return int(actual) == int(expected)
    except (TypeError, ValueError):
        return False


def _virtual_entry_actual_is(
    target_score: dict | None,
    ig: str,
    expected_actual: int,
) -> bool:
    if not isinstance(target_score, dict):
        return False
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, dict):
        return False
    entry = virtuals.get(ig)
    if not isinstance(entry, dict):
        return False
    actual = entry.get("actual")
    try:
        return int(actual) == int(expected_actual)
    except (TypeError, ValueError):
        return _virtual_entry_hit(target_score, ig, expected_actual)


def _virtual_actual_distance(
    target_score: dict | None,
    targets: dict[str, int],
) -> float | None:
    if not isinstance(target_score, dict):
        return None
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, dict):
        return None
    total = 0.0
    saw = False
    for ig, expected in targets.items():
        entry = virtuals.get(ig)
        if not isinstance(entry, dict):
            continue
        actual = entry.get("actual")
        try:
            total += abs(int(actual) - int(expected))
        except (TypeError, ValueError):
            continue
        saw = True
    if saw:
        return total
    return None


def _baseline_score_distance(
    baseline_score: Any,
    targets: dict[str, int],
) -> float | None:
    if not isinstance(baseline_score, Mapping):
        return None
    target_score = baseline_score.get("target_score")
    if isinstance(target_score, Mapping):
        baseline_score = target_score
    virtuals = baseline_score.get("virtuals")
    if isinstance(virtuals, Mapping):
        baseline_score = virtuals
    total = 0.0
    saw = False
    for ig, expected in targets.items():
        entry = baseline_score.get(ig)
        if entry is None:
            entry = baseline_score.get(int(ig)) if ig.isdigit() else None
        if not isinstance(entry, Mapping):
            continue
        actual = entry.get("actual")
        try:
            total += abs(int(actual) - int(expected))
        except (TypeError, ValueError):
            continue
        saw = True
    if saw:
        return total
    return None


def _probe_payload_dict(probe: dict) -> dict:
    payload = probe.get("payload")
    return payload if isinstance(payload, dict) else {}


def _probe_final_force_phys(probe: dict) -> dict[str, int]:
    payload = _probe_payload_dict(probe)
    value = payload.get("final_force_phys")
    if not isinstance(value, dict):
        value = payload.get("force_phys_targets")
    if not isinstance(value, dict):
        attempted = _probe_target_mapping(probe, "attempted_targets")
        protected = _probe_target_mapping(probe, "protected_targets")
        return {**protected, **attempted}
    out: dict[str, int] = {}
    for raw_ig, raw_phys in value.items():
        try:
            out[str(int(raw_ig))] = int(raw_phys)
        except (TypeError, ValueError):
            continue
    return out


def _probe_is_lower_drift_residual(probe: dict) -> bool:
    payload = _probe_payload_dict(probe)
    if payload.get("goal_kind") == "retained-case-c-lower-drift-residual":
        return True
    if (
        payload.get("source_probe_provenance_kind")
        == "retained-case-c-lower-drift-residual"
    ):
        return True
    attempted = _probe_target_mapping(probe, "attempted_targets")
    protected = _probe_target_mapping(probe, "protected_targets")
    return attempted.get("34") == 27 and protected.get("44") == 26


def _classify_retained_case_c_window_order_validation(
    probe: dict,
    result: dict,
) -> dict | None:
    if (
        probe.get("family_id")
        != RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    ):
        return None
    protected_targets = _probe_target_mapping(probe, "protected_targets")
    attempted_targets = _probe_target_mapping(probe, "attempted_targets")
    target_score = _validation_payload_dict(result, "target_score")
    protected_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in protected_targets.items()
    }
    attempted_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in attempted_targets.items()
    }
    if target_score is None:
        return {
            "classification": "unscoreable",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "protected_hits": protected_hits,
            "attempted_hits": attempted_hits,
            "first_divergence_moved_from_ig44_iter40": False,
        }
    protected_hit = all(protected_hits.values()) if protected_hits else False
    attempted_hit = all(attempted_hits.values()) if attempted_hits else False
    if protected_hit and attempted_hit:
        classification = "exact"
    elif protected_hit and not attempted_hit:
        classification = "protected-negative"
    elif not protected_hit:
        classification = "lost-protected"
    else:
        classification = "no-target-progress"
    return {
        "classification": classification,
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "protected_hits": protected_hits,
        "attempted_hits": attempted_hits,
    }


def _classify_retained_case_c_post_source_owner_backtrack_validation(
    probe: dict,
    result: dict,
) -> dict | None:
    if (
        probe.get("family_id")
        != RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
    ):
        return None
    protected_targets = _probe_target_mapping(probe, "protected_targets")
    attempted_targets = _probe_target_mapping(probe, "attempted_targets")
    target_score = _validation_payload_dict(result, "target_score")
    protected_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in protected_targets.items()
    }
    attempted_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in attempted_targets.items()
    }
    payload = _probe_payload_dict(probe)
    if target_score is None:
        return {
            "classification": "unscoreable",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "protected_hits": protected_hits,
            "attempted_hits": attempted_hits,
            "post_source_owner_backtrack": payload.get("post_source_owner_backtrack"),
        }
    protected_hit = all(protected_hits.values()) if protected_hits else False
    attempted_hit = all(attempted_hits.values()) if attempted_hits else False
    if protected_hit and attempted_hit:
        classification = "exact"
    elif protected_hit and not attempted_hit:
        classification = "protected-negative"
    elif not protected_hit:
        classification = "lost-protected"
    else:
        classification = "no-target-progress"
    return {
        "classification": classification,
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "protected_hits": protected_hits,
        "attempted_hits": attempted_hits,
        "post_source_owner_backtrack": payload.get("post_source_owner_backtrack"),
    }


def _classify_retained_case_c_target_live_range_validation(
    probe: dict,
    result: dict,
) -> dict | None:
    if (
        probe.get("family_id")
        not in RETAINED_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_IDS
    ):
        return None
    protected_targets = _probe_target_mapping(probe, "protected_targets")
    attempted_targets = _probe_target_mapping(probe, "attempted_targets")
    target_score = _validation_payload_dict(result, "target_score")
    protected_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in protected_targets.items()
    }
    attempted_hits = {
        ig: _virtual_entry_hit(target_score, ig, expected)
        for ig, expected in attempted_targets.items()
    }
    if target_score is None:
        return {
            "classification": "unscoreable",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "protected_hits": protected_hits,
            "attempted_hits": attempted_hits,
            "first_divergence_moved_from_ig44_iter40": False,
        }
    protected_hit = all(protected_hits.values()) if protected_hits else False
    attempted_hit = all(attempted_hits.values()) if attempted_hits else False
    if protected_hit and attempted_hit:
        classification = "exact"
    elif protected_hit and not attempted_hit:
        classification = "protected-negative"
    elif not protected_hit:
        classification = "lost-protected"
    else:
        classification = "no-target-progress"
    return {
        "classification": classification,
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "protected_hits": protected_hits,
        "attempted_hits": attempted_hits,
    }


def _first_divergence_moved_from_goal(
    result: dict,
    baseline: Mapping[str, Any] | None,
) -> bool:
    payload = result.get("validator_payload")
    movement = (
        payload.get("first_divergence_movement") if isinstance(payload, dict) else None
    )
    if isinstance(movement, dict):
        status = movement.get("status")
        if status in {"improved", "changed-flat-score", "changed", "moved"}:
            return True
        if status == "flat":
            return False
    first_divergence = (
        payload.get("first_divergence") if isinstance(payload, dict) else None
    )
    if not isinstance(first_divergence, dict):
        return False
    try:
        class_id = int(first_divergence.get("class_id", first_divergence.get("class")))
        iteration = int(first_divergence.get("iter", first_divergence.get("iteration")))
        ig_idx = int(first_divergence.get("ig_idx", first_divergence.get("ig")))
    except (TypeError, ValueError):
        return False
    if not isinstance(baseline, Mapping):
        baseline_tuple = (0, 40, 44)
    else:
        try:
            baseline_tuple = (
                int(baseline.get("class_id", baseline.get("class"))),
                int(baseline.get("iter", baseline.get("iteration"))),
                int(baseline.get("ig_idx", baseline.get("ig"))),
            )
        except (TypeError, ValueError):
            baseline_tuple = (0, 40, 44)
    return (class_id, iteration, ig_idx) != baseline_tuple


def _first_divergence_moved_from_ig44_iter40(result: dict) -> bool:
    return _first_divergence_moved_from_goal(
        result,
        {"class_id": 0, "iter": 40, "ig_idx": 44},
    )


def _classify_retained_case_c_simplify_order_validation(
    probe: dict,
    result: dict,
) -> dict | None:
    if (
        probe.get("family_id")
        != RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    ):
        return None
    protected_targets = _probe_target_mapping(probe, "protected_targets")
    attempted_targets = _probe_target_mapping(probe, "attempted_targets")
    final_force_phys = _probe_final_force_phys(probe)
    payload = _probe_payload_dict(probe)
    baseline_first_divergence = payload.get("baseline_first_divergence")
    baseline_first_divergence = (
        baseline_first_divergence
        if isinstance(baseline_first_divergence, Mapping)
        else None
    )
    lower_drift_residual = _probe_is_lower_drift_residual(probe)
    target_score = _validation_payload_dict(result, "target_score")
    protected_hits = {
        ig: _virtual_entry_actual_is(target_score, ig, expected)
        for ig, expected in protected_targets.items()
    }
    attempted_hits = {
        ig: _virtual_entry_actual_is(target_score, ig, expected)
        for ig, expected in attempted_targets.items()
    }
    final_hits = {
        ig: _virtual_entry_actual_is(target_score, ig, expected)
        for ig, expected in final_force_phys.items()
    }
    moved_from_goal = _first_divergence_moved_from_goal(
        result,
        baseline_first_divergence,
    )
    baseline_distance = _baseline_score_distance(
        payload.get("baseline_score"),
        final_force_phys,
    )
    candidate_distance = _virtual_actual_distance(target_score, final_force_phys)
    if target_score is None:
        return {
            "classification": "unscoreable",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "final_force_phys": final_force_phys,
            "protected_hits": protected_hits,
            "attempted_hits": attempted_hits,
            "final_hits": final_hits,
            "lower_drift_residual": lower_drift_residual,
            "first_divergence_moved_from_goal": False,
            "first_divergence_moved_from_ig44_iter40": False,
        }
    protected_hit = all(protected_hits.values()) if protected_hits else False
    attempted_hit = all(attempted_hits.values()) if attempted_hits else False
    final_hit = (
        all(final_hits.values()) if final_hits else (protected_hit and attempted_hit)
    )
    lower_drift_frontier = (
        lower_drift_residual
        and protected_hit
        and candidate_distance is not None
        and baseline_distance is not None
        and candidate_distance < baseline_distance
    )
    if final_hit:
        classification = "exact"
    elif lower_drift_residual and protected_hit and attempted_hit:
        classification = "residual-hit-protected-lower-drift"
    elif lower_drift_residual and not protected_hit:
        classification = "lost-lower-drift-progress"
    elif lower_drift_frontier:
        classification = "lower-drift-frontier"
    elif protected_hit and not attempted_hit:
        classification = "protected-negative"
    elif not protected_hit:
        classification = "lost-protected"
    else:
        classification = "no-target-progress"
    return {
        "classification": classification,
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "final_force_phys": final_force_phys,
        "protected_hits": protected_hits,
        "attempted_hits": attempted_hits,
        "final_hits": final_hits,
        "lower_drift_residual": lower_drift_residual,
        "candidate_final_distance": candidate_distance,
        "baseline_final_distance": baseline_distance,
        "first_divergence_moved_from_goal": moved_from_goal,
        "first_divergence_moved_from_ig44_iter40": (
            _first_divergence_moved_from_ig44_iter40(result)
        ),
    }


def _retained_window_probe_by_id(probe_payloads: list[dict]) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id")
        == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
        and probe.get("probe_id") is not None
    }


def _retained_window_candidate_summary(result: dict, probe: dict) -> dict:
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    source_attr = payload.get("source_attribution")
    source_attr_kind = (
        source_attr.get("kind") if isinstance(source_attr, dict) else None
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "source_diff": payload.get("source_diff"),
        "source_hunks": payload.get("source_hunks"),
        "window_order_label": payload.get("window_order_label"),
        "source_attribution_kind": source_attr_kind,
        "source_probe_provenance_kind": payload.get("source_probe_provenance_kind"),
        "call_return_source_probe": payload.get("call_return_source_probe"),
        "field_load_source_candidate": payload.get("field_load_source_candidate"),
        "pcode_first_def": payload.get("pcode_first_def"),
        "ranked_indexed_byte_source_candidate": payload.get(
            "ranked_indexed_byte_source_candidate"
        ),
        "ranked_end_pointer_source_candidate": payload.get(
            "ranked_end_pointer_source_candidate"
        ),
        "ranked_li_constant_source_candidate": payload.get(
            "ranked_li_constant_source_candidate"
        ),
        "ranked_pointer_walk_add_source_candidate": payload.get(
            "ranked_pointer_walk_add_source_candidate"
        ),
        "classification": result.get("retained_case_c_window_order_classification"),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _retained_case_c_window_order_continuation_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
) -> dict | None:
    probe_by_id = _retained_window_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id")
        == RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID
    ]
    if not probe_by_id and not retained_results:
        return None

    protected_targets: dict[str, int] = {}
    attempted_targets: dict[str, int] = {}
    for probe in probe_by_id.values():
        protected_targets.update(_probe_target_mapping(probe, "protected_targets"))
        attempted_targets.update(_probe_target_mapping(probe, "attempted_targets"))

    if not validation_results:
        return {
            "status": "materialized-not-scored",
            "kind": "retained-source-case-c-implicit-address-temp",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command"
            ],
        }

    classification_counts: dict[str, int] = {}
    best_candidates: list[dict] = []
    for result in retained_results:
        classification = result.get("retained_case_c_window_order_classification")
        kind = (
            classification.get("classification")
            if isinstance(classification, dict)
            else "unclassified"
        )
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        best_candidates.append(_retained_window_candidate_summary(result, probe))

    exact_count = classification_counts.get("exact", 0)
    status = "exact" if exact_count else "blocked"
    summary = {
        "status": status,
        "kind": "retained-source-case-c-implicit-address-temp-exhaustion",
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "evaluated_probe_count": len(retained_results),
        "protected_negative_count": classification_counts.get(
            "protected-negative",
            0,
        ),
        "lost_protected_count": classification_counts.get("lost-protected", 0),
        "no_target_progress_count": classification_counts.get(
            "no-target-progress",
            0,
        ),
        "exact_count": exact_count,
        "best_retained_candidates": best_candidates[:8],
    }
    if exact_count:
        summary["stop_condition"] = "exact-retained-window-order-continuation"
    else:
        summary["terminal_blocker"] = (
            "ranked-indexed-byte-window-order-probes-exhausted"
        )
        summary["next_source_lever_classes"] = [
            "target-aware-live-range-anchor",
            "target-aware-interference-shape",
            "target-aware-implicit-index-normalize",
            "target-aware-implicit-index-alias",
            "target-aware-implicit-base-alias",
            "target-aware-address-side-temp",
            "target-aware-value-side-temp",
            "target-aware-coupled-address-value",
        ]
    return summary


def _common_subexpr_coalesce_probe_by_id(
    probe_payloads: list[dict],
) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id")
        == RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
        and probe.get("probe_id") is not None
    }


def _common_subexpr_coalesce_diagnostic_terminal_summary(
    family_diagnostics: list[dict] | None,
) -> dict | None:
    if not family_diagnostics:
        return None
    for diagnostic in family_diagnostics:
        if (
            diagnostic.get("family_id")
            != RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
        ):
            continue
        reason = diagnostic.get("no_probe_reason")
        if not reason:
            return None
        matcher = (
            diagnostic.get("matcher_diagnostics")
            if isinstance(diagnostic.get("matcher_diagnostics"), dict)
            else {}
        )
        return {
            "status": "terminal-blocked",
            "kind": "retained-gpr-common-subexpr-coalesce-source",
            "materialized_probe_count": 0,
            "evaluated_probe_count": 0,
            "terminal_blocker": reason,
            "pair_diagnostics": matcher.get("pair_diagnostics", []),
        }
    return None


def _common_subexpr_coalesce_candidate_summary(
    result: dict,
    probe: dict,
    classification: dict | None = None,
) -> dict:
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "source_hunks": payload.get("source_hunks"),
        "coalesce_pair": payload.get("coalesce_pair"),
        "common_source_virtual": payload.get("common_source_virtual"),
        "common_source_bridge": payload.get("common_source_bridge"),
        "source_owner_strategy": payload.get("source_owner_strategy"),
        "source_owner_candidates": payload.get("source_owner_candidates"),
        "shared_temp": payload.get("shared_temp"),
        "shared_rhs": payload.get("shared_rhs"),
    }
    if classification is not None:
        candidate["classification"] = classification
    if validator_payload.get("error"):
        candidate["validator_error"] = validator_payload.get("error")
    return {key: value for key, value in candidate.items() if value is not None}


def _classify_common_subexpr_coalesce_validation(
    result: dict,
    probe: dict,
) -> dict:
    target_score = _validation_payload_dict(result, "target_score")
    protected_targets = _probe_target_mapping(probe, "protected_targets")
    attempted_targets = _probe_target_mapping(probe, "attempted_targets")
    final_targets = {**protected_targets, **attempted_targets}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    if target_score is None:
        out: dict[str, Any] = {"classification": "unscoreable"}
        if validator_payload.get("error"):
            out["validator_error"] = validator_payload.get("error")
        return out

    hit_targets = {
        ig: expected
        for ig, expected in final_targets.items()
        if _virtual_entry_actual_is(target_score, ig, expected)
    }
    missed_targets = {
        ig: expected
        for ig, expected in final_targets.items()
        if ig not in hit_targets
    }
    protected_hits = {
        ig: expected
        for ig, expected in protected_targets.items()
        if ig in hit_targets
    }
    attempted_hits = {
        ig: expected
        for ig, expected in attempted_targets.items()
        if ig in hit_targets
    }
    matched = _validation_numeric(target_score.get("matched"))
    targeted = _validation_numeric(target_score.get("targeted"))
    if final_targets and len(hit_targets) == len(final_targets):
        classification = "exact"
    elif protected_hits:
        classification = "protected-progress"
    elif attempted_hits or (matched is not None and matched > 0):
        classification = "residual-hit"
    else:
        classification = "no-target-progress"
    return {
        "classification": classification,
        "hit_targets": hit_targets,
        "missed_targets": missed_targets,
        "protected_hits": protected_hits,
        "attempted_hits": attempted_hits,
        "matched": matched,
        "targeted": targeted,
    }


def _retained_gpr_common_subexpr_coalesce_source_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
    family_diagnostics: list[dict] | None = None,
) -> dict | None:
    probe_by_id = _common_subexpr_coalesce_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id")
        == RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
    ]
    if not probe_by_id and not retained_results:
        return _common_subexpr_coalesce_diagnostic_terminal_summary(family_diagnostics)

    protected_targets: dict[str, int] = {}
    attempted_targets: dict[str, int] = {}
    candidates: list[dict] = []
    for probe in probe_by_id.values():
        protected_targets.update(_probe_target_mapping(probe, "protected_targets"))
        attempted_targets.update(_probe_target_mapping(probe, "attempted_targets"))
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        candidates.append(
            {
                "probe_id": probe.get("probe_id"),
                "coalesce_pair": payload.get("coalesce_pair"),
                "common_source_virtual": payload.get("common_source_virtual"),
                "common_source_bridge": payload.get("common_source_bridge"),
                "source_owner_strategy": payload.get("source_owner_strategy"),
                "source_owner_candidates": payload.get("source_owner_candidates"),
                "shared_temp": payload.get("shared_temp"),
                "source_hunks": payload.get("source_hunks"),
            }
        )

    if not validation_results:
        return {
            "status": "materialized-not-scored",
            "kind": "retained-gpr-common-subexpr-coalesce-source",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "coalesce_candidates": candidates[:8],
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command"
            ],
        }

    best_candidates: list[dict] = []
    classification_counts: dict[str, int] = {}
    residual_force_phys: dict[str, int] = {}
    preserved_force_phys: dict[str, int] = {}
    for result in retained_results:
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        classification = _classify_common_subexpr_coalesce_validation(result, probe)
        kind = str(classification.get("classification") or "unclassified")
        if result.get("outcome") == "retained-source-improvement":
            kind = "exact"
            classification = {**classification, "classification": kind}
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        missed = classification.get("missed_targets")
        if isinstance(missed, dict):
            residual_force_phys.update({
                str(ig): int(expected)
                for ig, expected in missed.items()
            })
        hit = classification.get("hit_targets")
        if isinstance(hit, dict):
            preserved_force_phys.update({
                str(ig): int(expected)
                for ig, expected in hit.items()
            })
        best_candidates.append(
            _common_subexpr_coalesce_candidate_summary(
                result,
                probe,
                classification=classification,
            )
        )
    exact_count = classification_counts.get("exact", 0)
    residual_hit_count = (
        classification_counts.get("protected-progress", 0)
        + classification_counts.get("residual-hit", 0)
    )
    unscoreable_count = classification_counts.get("unscoreable", 0)
    if exact_count:
        status = "exact"
    elif residual_hit_count:
        status = "residual-hit"
    elif unscoreable_count and unscoreable_count == len(retained_results):
        status = "unscoreable"
    else:
        status = "scored-negative"
    summary = {
        "status": status,
        "kind": "retained-gpr-common-subexpr-coalesce-source",
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "materialized_probe_count": len(probe_by_id),
        "evaluated_probe_count": len(retained_results),
        "exact_count": exact_count,
        "residual_hit_count": residual_hit_count,
        "protected_progress_count": classification_counts.get(
            "protected-progress",
            0,
        ),
        "unscoreable_count": unscoreable_count,
        "no_target_progress_count": classification_counts.get(
            "no-target-progress",
            0,
        ),
        "classification_counts": classification_counts,
        "best_retained_candidates": best_candidates[:8],
    }
    if residual_force_phys:
        summary["residual_force_phys"] = residual_force_phys
    if preserved_force_phys:
        summary["preserved_force_phys"] = preserved_force_phys
    if exact_count:
        summary["stop_condition"] = "exact-common-subexpr-coalesce-source"
    elif residual_hit_count:
        summary["stop_condition"] = "common-subexpr-coalesce-source-residual-hit"
    elif status == "unscoreable":
        summary["terminal_blocker"] = "common-subexpr-coalesce-source-unscoreable"
    else:
        summary["terminal_blocker"] = "common-subexpr-coalesce-source-probes-exhausted"
    return summary


def _bool_mask_probe_by_id(probe_payloads: list[dict]) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id") == PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID
        and probe.get("probe_id") is not None
    }


def _probe_target_assignments_mapping(probe: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for raw in probe.get("target_assignments") or ():
        if not isinstance(raw, str):
            continue
        match = re.match(r"ig(?P<ig>\d+)->r(?P<phys>\d+)$", raw)
        if match is None:
            continue
        out[match.group("ig")] = int(match.group("phys"))
    return out


def _bool_mask_probe_force_phys(probe: dict) -> dict[str, int]:
    payload = _probe_payload_dict(probe)
    value = payload.get("force_phys_targets")
    if isinstance(value, dict):
        out: dict[str, int] = {}
        for raw_ig, raw_phys in value.items():
            try:
                out[str(int(raw_ig))] = int(raw_phys)
            except (TypeError, ValueError):
                continue
        if out:
            return out
    attempted = _probe_target_mapping(probe, "attempted_targets")
    protected = _probe_target_mapping(probe, "protected_targets")
    if attempted or protected:
        return {**protected, **attempted}
    return _probe_target_assignments_mapping(probe)


def _classify_bool_mask_validation(result: dict, probe: dict) -> dict:
    target_score = _validation_payload_dict(result, "target_score")
    final_targets = _bool_mask_probe_force_phys(probe)
    if target_score is None:
        return {
            "classification": "unscoreable",
            "final_force_phys": final_targets,
            "hit_targets": {},
            "missed_targets": final_targets,
        }
    hit_targets = {
        ig: expected
        for ig, expected in final_targets.items()
        if _virtual_entry_actual_is(target_score, ig, expected)
    }
    missed_targets = {
        ig: expected for ig, expected in final_targets.items()
        if ig not in hit_targets
    }
    matched = _validation_numeric(target_score.get("matched"))
    targeted = _validation_numeric(target_score.get("targeted"))
    if result.get("outcome") == "retained-source-improvement":
        classification = "retained-source-improvement"
    elif final_targets and len(hit_targets) == len(final_targets):
        classification = "exact"
    elif hit_targets or (matched is not None and matched > 0):
        classification = "target-hit"
    else:
        classification = "no-target-hit"
    return {
        "classification": classification,
        "final_force_phys": final_targets,
        "hit_targets": hit_targets,
        "missed_targets": missed_targets,
        "matched": matched,
        "targeted": targeted,
    }


def _bool_mask_candidate_summary(
    result: dict,
    probe: dict,
    classification: dict | None = None,
) -> dict:
    payload = _probe_payload_dict(probe)
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "source_hunks": payload.get("source_hunks"),
        "strategy": payload.get("strategy"),
        "source_regions": payload.get("source_regions"),
        "mask_expression": payload.get("mask_expression"),
        "mask_temp_local": payload.get("mask_temp_local"),
        "original_callee": payload.get("original_callee"),
        "replacement_callee": payload.get("replacement_callee"),
        "target_assignments": probe.get("target_assignments"),
    }
    if classification is not None:
        candidate["classification"] = classification
    if validator_payload.get("error"):
        candidate["validator_error"] = validator_payload.get("error")
    return {key: value for key, value in candidate.items() if value is not None}


def _bool_mask_source_level_handoff(candidates: list[dict]) -> str:
    for candidate in candidates:
        strategy = candidate.get("strategy")
        if strategy in {
            "gpr-bool-mask-predicate-temp",
            "gpr-negated-field-mask-temp",
        }:
            expression = candidate.get("mask_expression") or "the predicate mask"
            return (
                "Bind or reschedule the remaining GPR bool/mask source expression "
                f"{expression}; the bounded temp spelling scored no target hit."
            )
    for candidate in candidates:
        replacement = candidate.get("replacement_callee")
        if replacement:
            return (
                "Try a different source-level dirty-wrapper placement around "
                f"{replacement}; direct call substitution scored no target hit."
            )
    return (
        "Bind or reschedule the remaining GPR bool/mask source expression; "
        "the bounded predicate and dirty-wrapper probes scored no target hit."
    )


def _pcode_only_gpr_bool_mask_temp_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
) -> dict | None:
    probe_by_id = _bool_mask_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id") == PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID
    ]
    probe_order = {
        str(probe.get("probe_id")): idx
        for idx, probe in enumerate(probe_payloads)
        if probe.get("probe_id") is not None
    }
    retained_results = sorted(
        retained_results,
        key=lambda result: _validation_rank_key(result, probe_order),
    )
    if not probe_by_id and not retained_results:
        return None

    if not validation_results or (probe_by_id and not retained_results):
        candidates = [
            {
                "probe_id": probe.get("probe_id"),
                "strategy": _probe_payload_dict(probe).get("strategy"),
                "source_regions": _probe_payload_dict(probe).get("source_regions"),
                "source_hunks": _probe_payload_dict(probe).get("source_hunks"),
                "target_assignments": probe.get("target_assignments"),
            }
            for probe in probe_by_id.values()
        ]
        return {
            "status": "materialized-not-scored",
            "kind": PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "candidates": candidates[:8],
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command"
            ],
        }

    classification_counts: dict[str, int] = {}
    best_candidates: list[dict] = []
    hit_targets: dict[str, int] = {}
    missed_targets: dict[str, int] = {}
    for result in retained_results:
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        classification = _classify_bool_mask_validation(result, probe)
        kind = str(classification.get("classification") or "unclassified")
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        hit = classification.get("hit_targets")
        if isinstance(hit, dict):
            hit_targets.update({str(ig): int(phys) for ig, phys in hit.items()})
        missed = classification.get("missed_targets")
        if isinstance(missed, dict):
            missed_targets.update({
                str(ig): int(phys) for ig, phys in missed.items()
            })
        best_candidates.append(
            _bool_mask_candidate_summary(
                result,
                probe,
                classification=classification,
            )
        )

    improvement_count = classification_counts.get("retained-source-improvement", 0)
    exact_count = classification_counts.get("exact", 0)
    target_hit_count = classification_counts.get("target-hit", 0)
    unscoreable_count = classification_counts.get("unscoreable", 0)
    terminal = not (improvement_count or exact_count or target_hit_count)
    if improvement_count or exact_count:
        status = "exact"
    elif target_hit_count:
        status = "target-hit"
    elif unscoreable_count and unscoreable_count == len(retained_results):
        status = "terminal-blocked"
        terminal_blocker = "bool-mask-source-probes-unscoreable"
    else:
        status = "terminal-blocked"
        terminal_blocker = "all-candidates-no-target-hit"
    summary = {
        "status": status,
        "kind": PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID,
        "exhausted_families": [PCODE_ONLY_GPR_BOOL_MASK_TEMP_REPAIR_FAMILY_ID],
        "materialized_probe_count": len(probe_by_id),
        "evaluated_probe_count": len(retained_results),
        "classification_counts": classification_counts,
        "exact_count": exact_count,
        "target_hit_count": target_hit_count,
        "retained_source_improvement_count": improvement_count,
        "unscoreable_count": unscoreable_count,
        "best_retained_candidates": best_candidates[:8],
    }
    if hit_targets:
        summary["hit_targets"] = hit_targets
    if missed_targets:
        summary["missed_targets"] = missed_targets
    if terminal:
        summary["terminal_blocker"] = terminal_blocker
        summary["terminal_blockers"] = [
            "exhausted-pcode-only-gpr-bool-mask-temp-repair",
            terminal_blocker,
        ]
        summary["source_level_handoff"] = _bool_mask_source_level_handoff(
            best_candidates
        )
    else:
        summary["stop_condition"] = (
            "pcode-only-gpr-bool-mask-retained-source-improvement"
            if improvement_count or exact_count
            else "pcode-only-gpr-bool-mask-target-hit"
        )
    return summary


def _retained_post_source_owner_probe_by_id(
    probe_payloads: list[dict],
) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id")
        == RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
        and probe.get("probe_id") is not None
    }


def _retained_post_source_owner_candidate_summary(
    result: dict,
    probe: dict,
) -> dict:
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "source_diff": payload.get("source_diff"),
        "window_order_label": payload.get("window_order_label"),
        "source_attribution_kind": (
            payload.get("source_attribution", {}).get("kind")
            if isinstance(payload.get("source_attribution"), dict)
            else None
        ),
        "ranked_indexed_byte_source_candidate": payload.get(
            "ranked_indexed_byte_source_candidate"
        ),
        "post_source_owner_backtrack": payload.get("post_source_owner_backtrack"),
        "classification": result.get(
            "retained_case_c_post_source_owner_backtrack_classification"
        ),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _post_source_owner_diagnostic_terminal_summary(
    family_diagnostics: list[dict] | None,
) -> dict | None:
    if not family_diagnostics:
        return None
    for diagnostic in family_diagnostics:
        if (
            diagnostic.get("family_id")
            != RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
        ):
            continue
        reason = diagnostic.get("no_probe_reason")
        if reason not in {
            "no-alternate-source-owner",
            "post-source-owner-exhausted",
        }:
            return None
        matcher = (
            diagnostic.get("matcher_diagnostics")
            if isinstance(diagnostic.get("matcher_diagnostics"), dict)
            else {}
        )
        return {
            "status": "terminal-blocked",
            "kind": "retained-source-case-c-post-source-owner-backtrack",
            "materialized_probe_count": 0,
            "evaluated_probe_count": 0,
            "terminal_blocker": reason,
            "attempted_targets": matcher.get("attempted_targets", {}),
            "protected_targets": matcher.get("protected_targets", {}),
            "skipped_current_owner_labels": matcher.get(
                "skipped_current_owner_labels",
                [],
            ),
            "selected_alternate_probe_count": matcher.get(
                "selected_alternate_probe_count",
                0,
            ),
        }
    return None


def _retained_case_c_post_source_owner_backtrack_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
    family_diagnostics: list[dict] | None = None,
) -> dict | None:
    probe_by_id = _retained_post_source_owner_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id")
        == RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID
    ]
    if not probe_by_id and not retained_results:
        return _post_source_owner_diagnostic_terminal_summary(family_diagnostics)

    protected_targets: dict[str, int] = {}
    attempted_targets: dict[str, int] = {}
    backtrack_candidates: list[dict] = []
    for probe in probe_by_id.values():
        protected_targets.update(_probe_target_mapping(probe, "protected_targets"))
        attempted_targets.update(_probe_target_mapping(probe, "attempted_targets"))
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        backtrack_candidates.append(
            {
                "probe_id": probe.get("probe_id"),
                "window_order_label": payload.get("window_order_label"),
                "post_source_owner_backtrack": payload.get(
                    "post_source_owner_backtrack"
                ),
                "ranked_indexed_byte_source_candidate": payload.get(
                    "ranked_indexed_byte_source_candidate"
                ),
            }
        )

    if not validation_results:
        return {
            "status": "materialized-not-scored",
            "kind": "retained-source-case-c-post-source-owner-backtrack",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "backtrack_candidates": backtrack_candidates[:8],
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command"
            ],
        }

    classification_counts: dict[str, int] = {}
    best_candidates: list[dict] = []
    for result in retained_results:
        classification = result.get(
            "retained_case_c_post_source_owner_backtrack_classification"
        )
        kind = (
            classification.get("classification")
            if isinstance(classification, dict)
            else "unclassified"
        )
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        best_candidates.append(
            _retained_post_source_owner_candidate_summary(result, probe)
        )

    exact_count = classification_counts.get("exact", 0)
    status = "scored-exact" if exact_count else "scored-negative"
    summary = {
        "status": status,
        "kind": "retained-source-case-c-post-source-owner-backtrack",
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "evaluated_probe_count": len(retained_results),
        "protected_negative_count": classification_counts.get(
            "protected-negative",
            0,
        ),
        "lost_protected_count": classification_counts.get("lost-protected", 0),
        "no_target_progress_count": classification_counts.get(
            "no-target-progress",
            0,
        ),
        "unscoreable_count": classification_counts.get("unscoreable", 0),
        "exact_count": exact_count,
        "best_retained_candidates": best_candidates[:8],
        "backtrack_candidates": backtrack_candidates[:8],
    }
    if exact_count:
        summary["stop_condition"] = "exact-post-source-owner-backtrack"
    else:
        summary["terminal_blocker"] = "post-source-owner-exhausted"
    return summary


def _retained_target_live_range_probe_by_id(
    probe_payloads: list[dict],
) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id") in RETAINED_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_IDS
        and probe.get("probe_id") is not None
    }


def _retained_target_live_range_candidate_summary(
    result: dict,
    probe: dict,
) -> dict:
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "source_diff": payload.get("source_diff"),
        "window_order_label": payload.get("window_order_label"),
        "source_probe_provenance_kind": payload.get("source_probe_provenance_kind"),
        "repair_goal": payload.get("repair_goal"),
        "ranked_repair_candidate": payload.get("ranked_repair_candidate"),
        "blocker_color_chain": (
            payload.get("repair_goal", {}).get("blocker_color_chain")
            if isinstance(payload.get("repair_goal"), dict)
            else None
        ),
        "classification": result.get(
            "retained_case_c_target_live_range_classification"
        ),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _retained_case_c_target_live_range_repair_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
    family_diagnostics: list[dict] | None = None,
) -> dict | None:
    probe_by_id = _retained_target_live_range_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id")
        in RETAINED_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_IDS
    ]
    source_owner_terminal_spans = _target_live_range_source_owner_terminal_spans(
        family_diagnostics
    )
    if not probe_by_id and not retained_results and not source_owner_terminal_spans:
        return None

    protected_targets: dict[str, int] = {}
    attempted_targets: dict[str, int] = {}
    exhausted_spans: list[dict] = []
    blocker_color_chains: list[list[dict]] = []
    for probe in probe_by_id.values():
        protected_targets.update(_probe_target_mapping(probe, "protected_targets"))
        attempted_targets.update(_probe_target_mapping(probe, "attempted_targets"))
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        repair_goal = (
            payload.get("repair_goal")
            if isinstance(payload.get("repair_goal"), dict)
            else {}
        )
        blocker_chain = repair_goal.get("blocker_color_chain")
        if isinstance(blocker_chain, list):
            normalized_chain = [
                dict(edge) for edge in blocker_chain if isinstance(edge, dict)
            ]
            if normalized_chain and normalized_chain not in blocker_color_chains:
                blocker_color_chains.append(normalized_chain)
        exhausted_spans.append(
            {
                "probe_id": probe.get("probe_id"),
                "source_probe_provenance_kind": payload.get(
                    "source_probe_provenance_kind"
                ),
                "ranked_repair_candidate": payload.get("ranked_repair_candidate"),
                "exhaustion_key": payload.get("exhaustion_key"),
                "blocker_color_chain": blocker_chain,
            }
        )

    if not validation_results:
        return {
            "status": "materialized-not-scored",
            "kind": "retained-source-case-c-target-live-range-interference",
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "blocker_color_chains": blocker_color_chains,
            "source_owner_terminal_spans": source_owner_terminal_spans,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "exhausted_strategy_spans": exhausted_spans,
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command"
            ],
        }

    classification_counts: dict[str, int] = {}
    best_candidates: list[dict] = []
    for result in retained_results:
        classification = result.get("retained_case_c_target_live_range_classification")
        kind = (
            classification.get("classification")
            if isinstance(classification, dict)
            else "unclassified"
        )
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        best_candidates.append(
            _retained_target_live_range_candidate_summary(result, probe)
        )

    exact_count = classification_counts.get("exact", 0)
    if not exact_count and source_owner_terminal_spans:
        source_owner_terminal_spans = _target_live_range_resolve_alternate_owner_spans(
            source_owner_terminal_spans,
            probe_by_id=probe_by_id,
            retained_results=retained_results,
        )
    status = "exact" if exact_count else "blocked"
    summary = {
        "status": status,
        "kind": "retained-source-case-c-target-live-range-interference",
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "evaluated_probe_count": len(retained_results),
        "protected_negative_count": classification_counts.get(
            "protected-negative",
            0,
        ),
        "lost_protected_count": classification_counts.get("lost-protected", 0),
        "no_target_progress_count": classification_counts.get(
            "no-target-progress",
            0,
        ),
        "unscoreable_count": classification_counts.get("unscoreable", 0),
        "exact_count": exact_count,
        "blocker_color_chains": blocker_color_chains,
        "best_retained_candidates": best_candidates[:8],
        "exhausted_strategy_spans": exhausted_spans[:8],
    }
    if exact_count:
        summary["stop_condition"] = "exact-retained-target-live-range-repair"
    else:
        if blocker_color_chains:
            summary["terminal_blocker"] = "blocker-color-chain-source-probes-exhausted"
            summary["dominant_blocker"] = "blocker-color-chain-source-probes"
        else:
            summary["terminal_blocker"] = (
                "target-aware-live-range-interference-probes-exhausted"
            )
        if source_owner_terminal_spans:
            summary["source_owner_terminal_spans"] = [
                _target_live_range_terminal_span_with_blocker(
                    span,
                    terminal_blocker=summary["terminal_blocker"],
                )
                for span in source_owner_terminal_spans
            ]
        summary["next_source_lever_classes"] = (
            _target_live_range_next_source_lever_classes(probe_by_id.values())
        )
    return summary


def _target_live_range_source_owner_terminal_spans(
    family_diagnostics: list[dict] | None,
) -> list[dict]:
    if not family_diagnostics:
        return []
    spans: list[dict] = []
    for diagnostic in family_diagnostics:
        if (
            diagnostic.get("family_id")
            == RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID
        ):
            matcher = (
                diagnostic.get("matcher_diagnostics")
                if isinstance(diagnostic.get("matcher_diagnostics"), dict)
                else {}
            )
            for raw_span in matcher.get("current_owner_span_updates", []) or []:
                if isinstance(raw_span, dict) and raw_span not in spans:
                    spans.append(dict(raw_span))
            continue
        if (
            diagnostic.get("family_id")
            not in RETAINED_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_IDS
        ):
            continue
        matcher = (
            diagnostic.get("matcher_diagnostics")
            if isinstance(diagnostic.get("matcher_diagnostics"), dict)
            else {}
        )
        for goal_diagnostic in matcher.get("repair_goal_diagnostics", []) or []:
            if not isinstance(goal_diagnostic, dict):
                continue
            span = _target_live_range_source_owner_terminal_span(
                diagnostic.get("family_id"),
                goal_diagnostic,
            )
            if span is not None and span not in spans:
                spans.append(span)
    return spans


def _target_live_range_source_owner_terminal_span(
    family_id: object,
    goal_diagnostic: dict,
) -> dict | None:
    repair_goal = (
        goal_diagnostic.get("repair_goal")
        if isinstance(goal_diagnostic.get("repair_goal"), dict)
        else {}
    )
    candidate_summary = (
        goal_diagnostic.get("repair_candidate_summary")
        if isinstance(goal_diagnostic.get("repair_candidate_summary"), dict)
        else {}
    )
    source_expression = repair_goal.get("source_expression")
    if source_expression is None:
        return None
    operand_owner = (
        repair_goal.get("operand_source_owner")
        if isinstance(repair_goal.get("operand_source_owner"), dict)
        else {}
    )
    operand_source = (
        operand_owner.get("source")
        if isinstance(operand_owner.get("source"), dict)
        else {}
    )
    first_def = (
        operand_source.get("first_def")
        if isinstance(operand_source.get("first_def"), dict)
        else {}
    )
    materialized_count = candidate_summary.get("materialized_count")
    candidate_count = candidate_summary.get("candidate_count")
    span = {
        "kind": "target-live-range-source-owner-terminal",
        "family_id": family_id,
        "target_ig": repair_goal.get("target_ig"),
        "target_phys": repair_goal.get("target_phys"),
        "interferer_ig": repair_goal.get("interferer_ig"),
        "interferer_phys": repair_goal.get("interferer_phys"),
        "source_expression": source_expression,
        "address_source_expression": repair_goal.get("address_source_expression"),
        "paired_source_expression": repair_goal.get("paired_source_expression"),
        "source_type": repair_goal.get("source_type"),
        "source_owner_kind": operand_source.get("kind"),
        "source_owner_confidence": operand_source.get("confidence"),
        "source_owner_base_virtual": operand_source.get("base_virtual"),
        "source_owner_first_def": first_def,
        "stack_symbol": _target_live_range_stack_symbol(first_def),
        "operand_index": operand_owner.get("operand_index"),
        "operand_virtual": operand_owner.get("operand_virtual"),
        "operand_assigned_reg": operand_owner.get("operand_assigned_reg"),
        "operand_live_range": operand_owner.get("operand_live_range"),
        "evidence_kind": (
            repair_goal.get("evidence", {}).get("kind")
            if isinstance(repair_goal.get("evidence"), dict)
            else None
        ),
        "status": goal_diagnostic.get("status"),
        "terminal_blocker": goal_diagnostic.get("terminal_blocker"),
        "candidate_count": candidate_count,
        "materialized_count": materialized_count,
        "rejection_reasons": candidate_summary.get("reasons"),
        "materialized_probe_labels": goal_diagnostic.get(
            "materialized_probe_labels",
            [],
        ),
    }
    blocked = (
        span["terminal_blocker"] is not None
        or span["status"] == "blocked"
        or materialized_count == 0
    )
    exhausted_current_owner = span["status"] == "materialized" and (
        isinstance(materialized_count, int) and materialized_count > 0
    )
    if not blocked and not exhausted_current_owner:
        return None
    return {key: value for key, value in span.items() if value not in (None, [], {})}


def _target_live_range_stack_symbol(first_def: dict) -> str | None:
    operands = first_def.get("operands")
    if not isinstance(operands, str):
        return None
    marker = "(r1)"
    end = operands.find(marker)
    if end < 0:
        return None
    comma = operands.rfind(",", 0, end)
    if comma < 0:
        return None
    symbol = operands[comma + 1 : end].strip()
    return symbol or None


def _target_live_range_terminal_span_with_blocker(
    span: dict,
    *,
    terminal_blocker: str,
) -> dict:
    out = dict(span)
    if out.get("next_source_owner_status") == "materialized":
        out.pop("terminal_blocker", None)
    elif not out.get("terminal_blocker"):
        out["terminal_blocker"] = terminal_blocker
    if out.get("status") == "materialized":
        out["source_owner_status"] = "current-source-owner-probes-exhausted"
        out.setdefault("next_source_owner_status", "not-discovered")
    return out


def _target_live_range_resolve_alternate_owner_spans(
    source_owner_terminal_spans: list[dict],
    *,
    probe_by_id: dict[str, dict],
    retained_results: list[dict],
) -> list[dict]:
    result_by_probe_id = {
        str(result.get("probe_id")): result
        for result in retained_results
        if result.get("probe_id") is not None
    }
    label_to_probe_id: dict[str, str] = {}
    for probe_id, probe in probe_by_id.items():
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        label = payload.get("window_order_label")
        if isinstance(label, str) and label:
            label_to_probe_id[label] = str(probe_id)

    resolved_spans: list[dict] = []
    for span in source_owner_terminal_spans:
        if span.get("next_source_owner_status") != "materialized":
            resolved_spans.append(span)
            continue
        raw_labels = span.get("alternate_source_owner_probe_labels")
        labels = (
            [label for label in raw_labels if isinstance(label, str) and label]
            if isinstance(raw_labels, list)
            else []
        )
        if not labels:
            resolved_spans.append(span)
            continue
        validations: list[dict] = []
        missing_validation = False
        for label in labels:
            probe_id = label_to_probe_id.get(label)
            if probe_id is None:
                missing_validation = True
                continue
            result = result_by_probe_id.get(probe_id)
            if result is None:
                missing_validation = True
                continue
            classification = result.get(
                "retained_case_c_target_live_range_classification"
            )
            validations.append(
                {
                    "probe_label": label,
                    "probe_id": probe_id,
                    "classification": (
                        classification.get("classification")
                        if isinstance(classification, dict)
                        else None
                    ),
                }
            )
        if missing_validation or not validations:
            resolved_spans.append(span)
            continue
        terminal_validation = all(
            validation.get("classification") == "protected-negative"
            for validation in validations
        )
        out = dict(span)
        out["alternate_source_owner_validation"] = validations
        if not terminal_validation:
            out.pop("terminal_blocker", None)
            resolved_spans.append(out)
            continue
        out["next_source_owner_status"] = "terminal-next-source-owner-exhausted"
        out["terminal_blocker"] = "next-source-owner-exhausted"
        resolved_spans.append(out)
    return resolved_spans


def _target_live_range_next_source_lever_classes(
    probes: Iterable[dict],
) -> list[str]:
    classes = [
        "target-aware-live-range-anchor",
        "target-aware-interference-shape",
        "target-aware-implicit-index-normalize",
        "target-aware-implicit-index-alias",
        "target-aware-implicit-base-alias",
        "target-aware-address-side-temp",
        "target-aware-value-side-temp",
        "target-aware-coupled-address-value",
    ]
    for probe in probes:
        if (
            probe.get("family_id")
            == RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
        ):
            return [
                *classes,
                "target-aware-scalar-interference-shape",
                "target-aware-scalar-pair-overlap",
            ]
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        repair_goal = (
            payload.get("repair_goal")
            if isinstance(payload.get("repair_goal"), dict)
            else {}
        )
        source_type = str(repair_goal.get("source_type") or "").lower()
        if source_type in {"f32", "float", "double"}:
            return [
                *classes,
                "target-aware-scalar-interference-shape",
                "target-aware-scalar-pair-overlap",
            ]
    return classes


def _retained_simplify_order_probe_by_id(
    probe_payloads: list[dict],
) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("family_id")
        == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
        and probe.get("probe_id") is not None
    }


def _retained_simplify_order_candidate_summary(
    result: dict,
    probe: dict,
) -> dict:
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    validator_payload = (
        result.get("validator_payload")
        if isinstance(result.get("validator_payload"), dict)
        else {}
    )
    candidate = {
        "probe_id": result.get("probe_id"),
        "source_retained": validator_payload.get(
            "source_retained",
            probe.get("candidate_path"),
        ),
        "source_file": validator_payload.get("source_file"),
        "pcdump_path": validator_payload.get("pcdump_path"),
        "remote_fallback": validator_payload.get("remote_fallback"),
        "target_score": _validation_payload_dict(result, "target_score"),
        "first_divergence": validator_payload.get("first_divergence"),
        "first_divergence_movement": validator_payload.get("first_divergence_movement"),
        "source_hunk": payload.get("source_hunk"),
        "source_diff": payload.get("source_diff"),
        "strategy": payload.get("strategy"),
        "source_span": payload.get("source_span"),
        "goal_kind": payload.get("goal_kind"),
        "final_force_phys": payload.get("final_force_phys"),
        "baseline_first_divergence": payload.get("baseline_first_divergence"),
        "classification": result.get("retained_case_c_simplify_order_classification"),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _retained_case_c_simplify_order_continuation_summary(
    probe_payloads: list[dict],
    validation_results: list[dict] | None,
) -> dict | None:
    probe_by_id = _retained_simplify_order_probe_by_id(probe_payloads)
    retained_results = [
        result
        for result in (validation_results or [])
        if result.get("family_id")
        == RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID
    ]
    if not probe_by_id and not retained_results:
        return None

    protected_targets: dict[str, int] = {}
    attempted_targets: dict[str, int] = {}
    final_force_phys: dict[str, int] = {}
    baseline_first_divergence: dict | None = None
    lower_drift_residual = False
    strategies: list[str] = []
    for probe in probe_by_id.values():
        protected_targets.update(_probe_target_mapping(probe, "protected_targets"))
        attempted_targets.update(_probe_target_mapping(probe, "attempted_targets"))
        final_force_phys.update(_probe_final_force_phys(probe))
        lower_drift_residual = lower_drift_residual or _probe_is_lower_drift_residual(
            probe
        )
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        if baseline_first_divergence is None and isinstance(
            payload.get("baseline_first_divergence"),
            dict,
        ):
            baseline_first_divergence = payload.get("baseline_first_divergence")
        strategy = payload.get("strategy")
        if isinstance(strategy, str) and strategy not in strategies:
            strategies.append(strategy)

    if not validation_results:
        return {
            "status": "materialized-not-scored",
            "kind": (
                "retained-source-case-c-lower-drift-residual"
                if lower_drift_residual
                else "retained-source-case-c-simplify-order-continuation"
            ),
            "objective": {
                "protected_targets": protected_targets,
                "attempted_targets": attempted_targets,
                "final_force_phys": final_force_phys,
            },
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "final_force_phys": final_force_phys,
            "baseline_first_divergence": baseline_first_divergence,
            "materialized_probe_count": len(probe_by_id),
            "evaluated_probe_count": 0,
            "strategies": strategies,
            "command_hints": [
                "rerun plan-transforms with --write-probes and --validate-command "
                "using debug target score-source --remote"
            ],
        }

    classification_counts: dict[str, int] = {}
    first_divergence_moved_count = 0
    protected_noop_count = 0
    candidates: list[dict] = []
    for result in retained_results:
        classification = result.get("retained_case_c_simplify_order_classification")
        kind = (
            classification.get("classification")
            if isinstance(classification, dict)
            else "unclassified"
        )
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        moved = bool(
            isinstance(classification, dict)
            and classification.get("first_divergence_moved_from_goal")
        )
        if not moved and not lower_drift_residual:
            moved = bool(
                isinstance(classification, dict)
                and classification.get("first_divergence_moved_from_ig44_iter40")
            )
        if moved:
            first_divergence_moved_count += 1
        if kind == "protected-negative" and not moved:
            protected_noop_count += 1
        probe = probe_by_id.get(str(result.get("probe_id")), {})
        candidates.append(_retained_simplify_order_candidate_summary(result, probe))

    def candidate_rank(candidate: dict) -> tuple:
        classification = candidate.get("classification")
        kind = (
            classification.get("classification")
            if isinstance(classification, dict)
            else "unclassified"
        )
        moved = bool(
            isinstance(classification, dict)
            and classification.get("first_divergence_moved_from_goal")
        )
        if not moved and not lower_drift_residual:
            moved = bool(
                isinstance(classification, dict)
                and classification.get("first_divergence_moved_from_ig44_iter40")
            )
        if lower_drift_residual:
            class_rank = {
                "exact": 0,
                "residual-hit-protected-lower-drift": 1,
                "lower-drift-frontier": 2 if moved else 3,
                "protected-negative": 4,
                "lost-lower-drift-progress": 5,
                "lost-protected": 6,
                "unscoreable": 7,
            }.get(kind, 8)
        else:
            class_rank = {
                "exact": 0,
                "protected-negative": 1 if moved else 2,
                "no-target-progress": 3,
                "lost-protected": 4,
                "unscoreable": 5,
            }.get(kind, 6)
        target_score = candidate.get("target_score")
        matched = (
            _validation_numeric(target_score.get("matched"))
            if isinstance(target_score, dict)
            else None
        )
        distance = (
            _validation_numeric(target_score.get("virtual_distance"))
            if isinstance(target_score, dict)
            else None
        )
        return (
            class_rank,
            -(matched if matched is not None else -1.0),
            distance if distance is not None else float("inf"),
            str(candidate.get("probe_id") or ""),
        )

    ranked_candidates = sorted(candidates, key=candidate_rank)
    exact_count = classification_counts.get("exact", 0)
    residual_hit_count = classification_counts.get(
        "residual-hit-protected-lower-drift",
        0,
    )
    status = (
        "exact"
        if exact_count
        else (
            "residual-hit"
            if lower_drift_residual and residual_hit_count
            else "exhausted"
        )
    )
    summary = {
        "status": status,
        "kind": (
            "retained-source-case-c-lower-drift-residual"
            if lower_drift_residual
            else "retained-source-case-c-simplify-order-continuation"
        ),
        "objective": {
            "protected_targets": protected_targets,
            "attempted_targets": attempted_targets,
            "final_force_phys": final_force_phys,
        },
        "ranked_by": [
            "target_score.virtuals",
            "first_divergence_movement",
            "source_hunk",
        ],
        "protected_targets": protected_targets,
        "attempted_targets": attempted_targets,
        "final_force_phys": final_force_phys,
        "baseline_first_divergence": baseline_first_divergence,
        "evaluated_probe_count": len(retained_results),
        "protected_negative_count": classification_counts.get(
            "protected-negative",
            0,
        ),
        "protected_noop_count": protected_noop_count,
        "residual_hit_count": residual_hit_count,
        "lower_drift_frontier_count": classification_counts.get(
            "lower-drift-frontier",
            0,
        ),
        "lost_lower_drift_count": classification_counts.get(
            "lost-lower-drift-progress",
            0,
        ),
        "first_divergence_moved_count": first_divergence_moved_count,
        "lost_protected_count": classification_counts.get("lost-protected", 0),
        "unscoreable_count": classification_counts.get("unscoreable", 0),
        "no_target_progress_count": classification_counts.get(
            "no-target-progress",
            0,
        ),
        "exact_count": exact_count,
        "strategies": strategies,
        "best_retained_candidates": ranked_candidates[:8],
    }
    if exact_count:
        summary["stop_condition"] = "exact-retained-case-c-simplify-order"
    elif lower_drift_residual and residual_hit_count:
        summary["stop_condition"] = "retained-case-c-lower-drift-residual-hit"
    elif first_divergence_moved_count:
        summary["terminal_blocker"] = (
            "bounded-remote-scored-exhaustion-no-ig34-residual-repair"
            if lower_drift_residual
            else (
                "bounded-remote-scored-exhaustion-preserved-ig34-and-moved-ig44-divergence"
            )
        )
    elif classification_counts.get("protected-negative", 0):
        summary["terminal_blocker"] = (
            "bounded-remote-scored-exhaustion-no-ig34-residual-repair"
            if lower_drift_residual
            else "bounded-remote-scored-exhaustion-no-simplify-order-movement"
        )
    elif classification_counts.get("lost-lower-drift-progress", 0):
        summary["terminal_blocker"] = (
            "bounded-remote-scored-exhaustion-lost-protected-only"
        )
    elif classification_counts.get("lost-protected", 0):
        summary["terminal_blocker"] = (
            "bounded-remote-scored-exhaustion-lost-protected-only"
        )
    else:
        summary["terminal_blocker"] = "remote-retained-source-unscoreable"
    return summary


def _validation_payload_dict(result: dict, key: str) -> dict | None:
    value = result.get(key)
    if isinstance(value, dict):
        return value
    payload = result.get("validator_payload")
    if not isinstance(payload, dict):
        return None
    nested = payload.get(key)
    return nested if isinstance(nested, dict) else None


def _validation_numeric(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validation_target_score_numeric(result: dict, key: str) -> float | None:
    target_score = _validation_payload_dict(result, "target_score")
    if target_score is None:
        return None
    return _validation_numeric(target_score.get(key))


def _validation_expression_score_numeric(result: dict, key: str) -> float | None:
    expression_score = _validation_payload_dict(result, "expression_score")
    if expression_score is None:
        return None
    return _validation_numeric(expression_score.get(key))


def _validation_best_score_numeric(result: dict, key: str) -> float | None:
    expression_value = _validation_expression_score_numeric(result, key)
    if expression_value is not None:
        return expression_value
    return _validation_target_score_numeric(result, key)


def _validation_frame_delta(result: dict) -> float | None:
    for container in (
        _validation_payload_dict(result, "structural_guard"),
        _validation_payload_dict(result, "target_score"),
        result.get("validator_payload"),
    ):
        if not isinstance(container, dict):
            continue
        for key in ("frame_delta", "frame_size_delta", "local_frame_delta"):
            value = _validation_numeric(container.get(key))
            if value is not None:
                return abs(value)
    return None


def _validation_structural_guard_accepted(result: dict) -> bool | None:
    guard = _validation_payload_dict(result, "structural_guard")
    if guard is None:
        return None
    accepted = guard.get("accepted")
    if isinstance(accepted, bool):
        return accepted
    return _payload_bool(accepted)


def _validation_false_positive_virtual_id_hit_count(result: dict) -> int:
    expression_score = _validation_payload_dict(result, "expression_score")
    if expression_score is not None:
        value = _validation_numeric(
            expression_score.get("false_positive_virtual_id_hit_count")
        )
        if value is not None:
            return int(value)
    payload = result.get("validator_payload")
    if isinstance(payload, dict):
        value = _validation_numeric(payload.get("false_positive_virtual_id_hit_count"))
        if value is not None:
            return int(value)
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        value = _validation_numeric(evidence.get("false_positive_virtual_id_hit_count"))
        if value is not None:
            return int(value)
    return 0


def _validation_has_raw_target_score_progress(result: dict) -> bool:
    matched = _validation_target_score_numeric(result, "matched")
    if matched is None:
        return False
    return matched > 0


def _validation_expression_score_regressed(result: dict) -> bool:
    matched = _validation_expression_score_numeric(result, "matched")
    targeted = _validation_expression_score_numeric(result, "targeted")
    if matched is None or targeted is None:
        return False
    return matched < targeted


def _validation_normalized_diff_lines(result: dict) -> float | None:
    guard = _validation_payload_dict(result, "structural_guard")
    if guard is not None:
        value = _validation_numeric(guard.get("normalized_diff_lines"))
        if value is not None:
            return value
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        guard = evidence.get("structural_guard")
        if isinstance(guard, dict):
            value = _validation_numeric(guard.get("normalized_diff_lines"))
            if value is not None:
                return value
    payload = result.get("validator_payload")
    if isinstance(payload, dict):
        value = _validation_numeric(payload.get("normalized_diff_lines"))
        if value is not None:
            return value
    return None


def _validation_opcode_similarity(result: dict) -> float | None:
    guard = _validation_payload_dict(result, "structural_guard")
    if guard is not None:
        value = _validation_numeric(guard.get("opcode_similarity"))
        if value is not None:
            return value
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        guard = evidence.get("structural_guard")
        if isinstance(guard, dict):
            value = _validation_numeric(guard.get("opcode_similarity"))
            if value is not None:
                return value
    payload = result.get("validator_payload")
    if isinstance(payload, dict):
        value = _validation_numeric(payload.get("opcode_similarity"))
        if value is not None:
            return value
    return None


def _validation_expression_preserved(
    result: dict,
    *,
    min_targeted: int = 6,
) -> bool:
    matched = _validation_expression_score_numeric(result, "matched")
    targeted = _validation_expression_score_numeric(result, "targeted")
    if matched is None or targeted is None:
        return False
    return (
        matched == targeted
        and targeted >= min_targeted
        and _validation_false_positive_virtual_id_hit_count(result) == 0
    )


def _validation_target_matched_at_least(
    result: dict,
    *,
    minimum: int = 5,
) -> bool:
    matched = _validation_target_score_numeric(result, "matched")
    return matched is not None and matched >= minimum


def _validation_probe_payload_by_id(probe_payloads: list[dict]) -> dict[str, dict]:
    return {
        str(probe.get("probe_id")): probe
        for probe in probe_payloads
        if probe.get("probe_id") is not None
    }


def _validation_probe_strategy(probe: dict | None) -> str | None:
    if not isinstance(probe, dict):
        return None
    payload = probe.get("payload")
    if isinstance(payload, dict) and payload.get("strategy") is not None:
        return str(payload.get("strategy"))
    if probe.get("strategy") is not None:
        return str(probe.get("strategy"))
    return None


def _validation_structural_guard_compact(result: dict) -> dict:
    guard = _validation_payload_dict(result, "structural_guard")
    if guard is None:
        evidence = result.get("evidence")
        if isinstance(evidence, dict) and isinstance(
            evidence.get("structural_guard"),
            dict,
        ):
            guard = evidence["structural_guard"]
    if guard is None:
        return {}
    compact = {}
    for key in (
        "classification_primary",
        "normalized_diff_lines",
        "opcode_similarity",
        "line_delta",
        "hunk_count",
    ):
        if key in guard:
            compact[key] = guard[key]
    return compact


def _validation_callarg_local_evidence(
    result: dict,
    probe_by_id: Mapping[str, dict],
) -> dict:
    evidence = {
        "probe_id": result.get("probe_id"),
        "family_id": result.get("family_id"),
        "outcome": result.get("outcome"),
    }
    target_score = _validation_payload_dict(result, "target_score")
    if target_score is not None:
        evidence["target_score"] = {
            key: target_score[key]
            for key in ("total", "matched", "targeted", "virtual_distance")
            if key in target_score
        }
    expression_score = _validation_payload_dict(result, "expression_score")
    if expression_score is not None:
        evidence["expression_score"] = {
            key: expression_score[key]
            for key in (
                "matched",
                "targeted",
                "virtual_distance",
                "false_positive_virtual_id_hit_count",
            )
            if key in expression_score
        }
    structural_guard = _validation_structural_guard_compact(result)
    if structural_guard:
        evidence["structural_guard"] = structural_guard
    probe = probe_by_id.get(str(result.get("probe_id")))
    strategy = _validation_probe_strategy(probe)
    if strategy is not None:
        evidence["strategy"] = strategy
    false_positive_count = _validation_false_positive_virtual_id_hit_count(result)
    evidence["false_positive_virtual_id_hit_count"] = false_positive_count
    normalized_lines = _validation_normalized_diff_lines(result)
    if normalized_lines is not None:
        evidence["normalized_diff_lines"] = normalized_lines
    opcode_similarity = _validation_opcode_similarity(result)
    if opcode_similarity is not None:
        evidence["opcode_similarity"] = opcode_similarity
    return evidence


def _validation_callarg_local_frontier_summary(
    probe_payloads: list[dict],
    validation_results: list[dict],
) -> dict | None:
    threshold = 30
    callarg_results = [
        result
        for result in validation_results
        if result.get("family_id") == "callarg_local_structural_repair"
    ]
    if not callarg_results:
        return None

    probe_by_id = _validation_probe_payload_by_id(probe_payloads)
    probe_order = {probe_id: index for index, probe_id in enumerate(probe_by_id)}

    def result_order(result: dict) -> int:
        return probe_order.get(str(result.get("probe_id")), len(probe_order))

    def expression_key(result: dict) -> tuple:
        normalized = _validation_normalized_diff_lines(result)
        target_matched = _validation_target_score_numeric(result, "matched")
        opcode_similarity = _validation_opcode_similarity(result)
        virtual_distance = _validation_expression_score_numeric(
            result,
            "virtual_distance",
        )
        return (
            normalized if normalized is not None else float("inf"),
            -(target_matched if target_matched is not None else -1.0),
            -(opcode_similarity if opcode_similarity is not None else -1.0),
            virtual_distance if virtual_distance is not None else float("inf"),
            result_order(result),
        )

    def structural_key(result: dict) -> tuple:
        normalized = _validation_normalized_diff_lines(result)
        opcode_similarity = _validation_opcode_similarity(result)
        expression_matched = _validation_expression_score_numeric(result, "matched")
        target_matched = _validation_target_score_numeric(result, "matched")
        return (
            normalized if normalized is not None else float("inf"),
            -(opcode_similarity if opcode_similarity is not None else -1.0),
            -(expression_matched if expression_matched is not None else -1.0),
            -(target_matched if target_matched is not None else -1.0),
            _validation_false_positive_virtual_id_hit_count(result),
            result_order(result),
        )

    expression_preserving = [
        result
        for result in callarg_results
        if _validation_expression_preserved(result, min_targeted=6)
    ]
    best_expression = (
        sorted(expression_preserving, key=expression_key)[0]
        if expression_preserving
        else None
    )
    structural_candidates = [
        result
        for result in callarg_results
        if _validation_normalized_diff_lines(result) is not None
    ]
    best_structural = (
        sorted(structural_candidates or callarg_results, key=structural_key)[0]
        if callarg_results
        else None
    )
    raw_target_false_progress_results = [
        result
        for result in sorted(callarg_results, key=structural_key)
        if _validation_target_matched_at_least(result, minimum=5)
        and (
            _validation_expression_score_regressed(result)
            or _validation_false_positive_virtual_id_hit_count(result) > 0
        )
    ]

    stop_condition_met = any(
        _validation_expression_preserved(result, min_targeted=6)
        and _validation_target_matched_at_least(result, minimum=5)
        and (normalized := _validation_normalized_diff_lines(result)) is not None
        and normalized < threshold
        for result in callarg_results
    )

    terminal_blockers: list[str] = []
    inline_boundary_opcode_drift: dict | None = None
    expression_norms = [
        normalized
        for result in expression_preserving
        if (normalized := _validation_normalized_diff_lines(result)) is not None
    ]
    subthreshold_results = [
        result
        for result in callarg_results
        if (normalized := _validation_normalized_diff_lines(result)) is not None
        and normalized < threshold
    ]
    subthreshold_preserving = [
        result
        for result in subthreshold_results
        if _validation_expression_preserved(result, min_targeted=6)
    ]
    raw_target_progress = [
        result
        for result in callarg_results
        if _validation_target_matched_at_least(result, minimum=5)
    ]
    if not stop_condition_met:
        if expression_norms and min(expression_norms) >= threshold:
            terminal_blockers.append("structural-ceiling-with-protected-anchors")
            if best_expression is not None:
                drift = _validation_structural_guard_compact(best_expression)
                if drift:
                    inline_boundary_opcode_drift = drift
                    terminal_blockers.append("inline-boundary-opcode-drift")
        if subthreshold_results and not subthreshold_preserving:
            terminal_blockers.append("sub30-candidates-lost-protected-anchors")
        if raw_target_progress and all(
            _validation_expression_score_regressed(result)
            or _validation_false_positive_virtual_id_hit_count(result) > 0
            for result in raw_target_progress
        ):
            terminal_blockers.append("raw-target-progress-expression-regressed")

    frontier_summary = {
        "threshold_normalized_diff_lines": threshold,
        "best_expression_preserving": (
            _validation_callarg_local_evidence(best_expression, probe_by_id)
            if best_expression is not None
            else None
        ),
        "best_structural": (
            _validation_callarg_local_evidence(best_structural, probe_by_id)
            if best_structural is not None
            else None
        ),
        "raw_target_false_progress": [
            _validation_callarg_local_evidence(result, probe_by_id)
            for result in raw_target_false_progress_results
        ],
        "stop_condition_met": stop_condition_met,
        "terminal_blockers": terminal_blockers,
    }
    if inline_boundary_opcode_drift is not None:
        frontier_summary["inline_boundary_opcode_drift"] = inline_boundary_opcode_drift
    return frontier_summary


def _validation_retained_case_c_sensitivity_summary(
    probe_payloads: list[dict],
    validation_results: list[dict],
) -> dict | None:
    retained_results = [
        result
        for result in validation_results
        if result.get("family_id") == "retained_gpr_case_c_sensitivity_search"
    ]
    if not retained_results:
        return None
    probe_order = {
        str(probe.get("probe_id")): idx
        for idx, probe in enumerate(probe_payloads)
        if probe.get("probe_id") is not None
    }
    ranked = sorted(
        retained_results,
        key=lambda result: _validation_rank_key(result, probe_order),
    )

    def evidence_for(result: dict | None) -> dict | None:
        if result is None:
            return None
        evidence = result.get("evidence")
        return dict(evidence) if isinstance(evidence, dict) else None

    def movement_status(result: dict) -> str | None:
        payload = result.get("validator_payload")
        movement = (
            payload.get("first_divergence_movement")
            if isinstance(
                payload,
                dict,
            )
            else None
        )
        if isinstance(movement, dict) and movement.get("status") is not None:
            return str(movement["status"])
        movement = result.get("target_assignment_movement")
        if isinstance(movement, dict) and movement:
            return "improved"
        return None

    moving = [
        result
        for result in ranked
        if result.get("outcome") == "retained-source-improvement"
        or _validation_has_raw_target_score_progress(result)
        or movement_status(result) in {"improved", "changed-flat-score"}
    ]
    flat = [
        result
        for result in ranked
        if result.get("outcome") == "negative-evidence"
        and not _validation_has_raw_target_score_progress(result)
        and movement_status(result) in {None, "flat"}
    ]
    blocked = [result for result in ranked if result.get("outcome") == "blocked"]
    best = ranked[0] if ranked else None
    best_movement = moving[0] if moving else None
    stop_condition_met = best_movement is not None
    summary = {
        "ranked_by": [
            "target_score.virtuals",
            "first_divergence_movement",
        ],
        "evaluated_candidates": len(retained_results),
        "flat_candidates": len(flat),
        "blocked_candidates": len(blocked),
        "stop_condition_met": stop_condition_met,
        "best_target_score": evidence_for(best),
        "best_movement": evidence_for(best_movement),
        "ranked_case_c_candidates": [
            evidence
            for result in ranked[:8]
            if (evidence := evidence_for(result)) is not None
        ],
    }
    if not stop_condition_met:
        summary["terminal_blockers"] = ["flat-retained-case-c-sensitivity-exhausted"]
    return summary


def _validation_rank_key(result: dict, probe_order: Mapping[str, int]) -> tuple:
    probe_id = str(result.get("probe_id"))
    guard_accepted = _validation_structural_guard_accepted(result)
    guard_rank = 0 if guard_accepted is True else 1 if guard_accepted is None else 2
    matched = _validation_best_score_numeric(result, "matched")
    distance = _validation_best_score_numeric(result, "virtual_distance")
    if distance is None:
        distance = _validation_best_score_numeric(result, "score")
    frame_delta = _validation_frame_delta(result)
    return (
        guard_rank,
        -(matched if matched is not None else -1.0),
        distance if distance is not None else float("inf"),
        frame_delta if frame_delta is not None else float("inf"),
        probe_order.get(probe_id, len(probe_order)),
    )


def _ranked_guarded_validation_partials(
    probe_payloads: list[dict],
    validation_results: list[dict],
) -> list[dict]:
    probe_order = {
        str(probe.get("probe_id")): idx
        for idx, probe in enumerate(probe_payloads)
        if probe.get("probe_id") is not None
    }
    scored = [
        result
        for result in validation_results
        if (
            _validation_payload_dict(result, "target_score") is not None
            or _validation_payload_dict(result, "expression_score") is not None
        )
    ]
    ranked = sorted(
        scored, key=lambda result: _validation_rank_key(result, probe_order)
    )
    return [
        dict(result.get("evidence") or {})
        for result in ranked[:8]
        if isinstance(result.get("evidence"), dict)
    ]


def _summarize_transform_validations(
    probe_payloads: list[dict],
    validation_results: list[dict],
) -> dict:
    outcomes: dict[str, int] = {}
    for result in validation_results:
        outcome = str(result.get("outcome") or "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    evaluated_ids = [
        str(result.get("probe_id"))
        for result in validation_results
        if result.get("probe_id") is not None
    ]
    evaluated_set = set(evaluated_ids)
    remaining_ids = [
        str(probe.get("probe_id"))
        for probe in probe_payloads
        if probe.get("probe_id") is not None
        and str(probe.get("probe_id")) not in evaluated_set
    ]
    if not probe_payloads:
        stop_condition = "no-probes"
    elif outcomes.get("retained-source-improvement"):
        stop_condition = "retained-source-improvement"
    elif outcomes.get("larger-refactor-recommended"):
        stop_condition = "larger-refactor-recommended"
    elif validation_results and all(
        result.get("outcome") == "negative-evidence" for result in validation_results
    ):
        stop_condition = "exhausted-negative-evidence"
    elif validation_results and all(
        result.get("outcome") == "blocked" for result in validation_results
    ):
        stop_condition = "blocked"
    elif validation_results:
        stop_condition = "mixed"
    else:
        stop_condition = "not-run"
    evidence_counts: dict[str, int] = {}
    for result in validation_results:
        evidence = result.get("evidence")
        if not isinstance(evidence, dict):
            continue
        outcome = str(evidence.get("outcome") or "unknown")
        evidence_counts[outcome] = evidence_counts.get(outcome, 0) + 1
    summary = {
        "stop_condition": stop_condition,
        "evaluated_probes": len(validation_results),
        "remaining_probe_ids": remaining_ids,
        "outcomes": outcomes,
        "evidence_counts": evidence_counts,
    }
    ranked_partials = _ranked_guarded_validation_partials(
        probe_payloads,
        validation_results,
    )
    if ranked_partials:
        summary["ranked_guarded_partials"] = ranked_partials
    callarg_frontier_summary = _validation_callarg_local_frontier_summary(
        probe_payloads,
        validation_results,
    )
    if callarg_frontier_summary is not None:
        summary["callarg_local_frontier_summary"] = callarg_frontier_summary
    retained_case_c_summary = _validation_retained_case_c_sensitivity_summary(
        probe_payloads,
        validation_results,
    )
    if retained_case_c_summary is not None:
        summary["retained_case_c_sensitivity_summary"] = retained_case_c_summary
        summary["ranked_case_c_candidates"] = retained_case_c_summary[
            "ranked_case_c_candidates"
        ]
        if not retained_case_c_summary.get("stop_condition_met"):
            blockers = summary.setdefault("terminal_blockers", [])
            blockers.append("exhausted-retained-gpr-case-c-sensitivity-search")
            for blocker in retained_case_c_summary.get("terminal_blockers", []):
                if blocker not in blockers:
                    blockers.append(blocker)
    retained_window_summary = _retained_case_c_window_order_continuation_summary(
        probe_payloads,
        validation_results,
    )
    if retained_window_summary is not None:
        summary["retained_case_c_window_order_continuation_summary"] = (
            retained_window_summary
        )
        if retained_window_summary.get("status") == "exact":
            summary["stop_condition"] = "exact-retained-window-order-continuation"
        elif retained_window_summary.get("status") == "blocked":
            blockers = summary.setdefault("terminal_blockers", [])
            blocker = retained_window_summary.get("terminal_blocker")
            if blocker and blocker not in blockers:
                blockers.append(blocker)
    retained_post_source_owner_summary = (
        _retained_case_c_post_source_owner_backtrack_summary(
            probe_payloads,
            validation_results,
        )
    )
    if retained_post_source_owner_summary is not None:
        summary["retained_case_c_post_source_owner_backtrack_summary"] = (
            retained_post_source_owner_summary
        )
        if retained_post_source_owner_summary.get("status") == "scored-exact":
            summary["stop_condition"] = "exact-post-source-owner-backtrack"
        elif retained_post_source_owner_summary.get("status") in {
            "scored-negative",
            "terminal-blocked",
        }:
            blockers = summary.setdefault("terminal_blockers", [])
            blocker = retained_post_source_owner_summary.get("terminal_blocker")
            if blocker and blocker not in blockers:
                blockers.append(blocker)
    retained_target_live_range_summary = (
        _retained_case_c_target_live_range_repair_summary(
            probe_payloads,
            validation_results,
        )
    )
    if retained_target_live_range_summary is not None:
        summary["retained_case_c_target_live_range_repair_summary"] = (
            retained_target_live_range_summary
        )
        if retained_target_live_range_summary.get("status") == "exact":
            summary["stop_condition"] = "exact-retained-target-live-range-repair"
        elif retained_target_live_range_summary.get("status") == "blocked":
            blockers = summary.setdefault("terminal_blockers", [])
            blocker = retained_target_live_range_summary.get("terminal_blocker")
            if blocker and blocker not in blockers:
                blockers.append(blocker)
    retained_simplify_order_summary = (
        _retained_case_c_simplify_order_continuation_summary(
            probe_payloads,
            validation_results,
        )
    )
    if retained_simplify_order_summary is not None:
        summary["retained_case_c_simplify_order_continuation_summary"] = (
            retained_simplify_order_summary
        )
        if retained_simplify_order_summary.get("status") == "exact":
            summary["stop_condition"] = "exact-retained-case-c-simplify-order"
        elif retained_simplify_order_summary.get("status") == "residual-hit":
            summary["stop_condition"] = "retained-case-c-lower-drift-residual-hit"
        elif retained_simplify_order_summary.get("status") == "exhausted":
            blockers = summary.setdefault("terminal_blockers", [])
            blocker = retained_simplify_order_summary.get("terminal_blocker")
            if blocker and blocker not in blockers:
                blockers.append(blocker)
    stack_array_proof = _stack_array_node_set_terminal_proof(
        probe_payloads,
        validation_results,
    )
    if stack_array_proof is not None:
        summary["stack_array_base_terminal_proof"] = stack_array_proof
        summary["terminal_proof"] = stack_array_proof
        blockers = summary.setdefault("terminal_blockers", [])
        blocker = stack_array_proof.get("terminal_reason")
        if blocker and blocker not in blockers:
            blockers.append(blocker)
    bool_mask_summary = _pcode_only_gpr_bool_mask_temp_summary(
        probe_payloads,
        validation_results,
    )
    if bool_mask_summary is not None:
        summary["pcode_only_gpr_bool_mask_temp_repair_summary"] = (
            bool_mask_summary
        )
        if bool_mask_summary.get("status") == "terminal-blocked":
            summary["terminal_proof"] = bool_mask_summary
            blockers = summary.setdefault("terminal_blockers", [])
            for blocker in bool_mask_summary.get("terminal_blockers", []):
                if blocker and blocker not in blockers:
                    blockers.append(blocker)
        elif bool_mask_summary.get("stop_condition"):
            summary["stop_condition"] = bool_mask_summary["stop_condition"]
    if (
        validation_results
        and not outcomes.get("retained-source-improvement")
        and any(
            result.get("family_id") == "coupled_fpr_coalesce_product_repair"
            for result in validation_results
        )
    ):
        summary["terminal_blockers"] = ["exhausted-coupled-fpr-coalesce-product-repair"]
        if any(
            _validation_structural_guard_accepted(result) is False
            for result in validation_results
            if result.get("family_id") == "coupled_fpr_coalesce_product_repair"
        ):
            summary["terminal_blockers"].append("structural-guard-rejected")
    if (
        validation_results
        and not outcomes.get("retained-source-improvement")
        and any(
            result.get("family_id") == "pcode_only_fpr_callarg_temp_repair"
            for result in validation_results
        )
    ):
        blockers = summary.setdefault("terminal_blockers", [])
        blockers.append("exhausted-pcode-only-fpr-callarg-temp-repair")
        if any(
            _validation_structural_guard_accepted(result) is False
            for result in validation_results
            if result.get("family_id") == "pcode_only_fpr_callarg_temp_repair"
        ):
            blockers.append("structural-guard-rejected")
    if (
        validation_results
        and not outcomes.get("retained-source-improvement")
        and any(
            result.get("family_id") == "callarg_local_structural_repair"
            for result in validation_results
        )
    ):
        frontier_stop_met = bool(
            callarg_frontier_summary
            and callarg_frontier_summary.get("stop_condition_met")
        )
        if not frontier_stop_met:
            blockers = summary.setdefault("terminal_blockers", [])
            blockers.append("exhausted-callarg-local-structural-repair")
            if any(
                _validation_structural_guard_accepted(result) is False
                for result in validation_results
                if result.get("family_id") == "callarg_local_structural_repair"
            ):
                blockers.append("structural-guard-rejected")
            raw_progress = [
                result
                for result in validation_results
                if result.get("family_id") == "callarg_local_structural_repair"
                and _validation_has_raw_target_score_progress(result)
            ]
            if raw_progress and all(
                _validation_expression_score_regressed(result)
                or _validation_false_positive_virtual_id_hit_count(result) > 0
                for result in raw_progress
            ):
                if "raw-target-progress-expression-regressed" not in blockers:
                    blockers.append("raw-target-progress-expression-regressed")
            if callarg_frontier_summary is not None:
                for blocker in callarg_frontier_summary.get("terminal_blockers", []):
                    if blocker not in blockers:
                        blockers.append(blocker)
    return summary


def _assignment_progress(meta: dict | None) -> dict:
    proof = (meta or {}).get("proof_assignments") or {}
    return {
        "satisfied": [
            _format_assignment(entry, status="satisfied")
            for entry in proof.get("satisfied", []) or []
            if isinstance(entry, dict)
        ],
        "blocked": [
            _format_assignment(entry, status="blocked")
            for entry in proof.get("blocked", []) or []
            if isinstance(entry, dict)
        ],
        "abstained": [
            _format_assignment(entry, status="abstained")
            for entry in proof.get("abstained", []) or []
            if isinstance(entry, dict)
        ],
    }


def _assignment_igs(meta: dict | None) -> set[int]:
    proof = (meta or {}).get("proof_assignments") or {}
    out: set[int] = set()
    for bucket in ("satisfied", "blocked", "abstained"):
        for entry in proof.get(bucket, []) or []:
            if not isinstance(entry, dict):
                continue
            try:
                out.add(int(entry["original_ig"]))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _assignment_clusters(meta: dict | None) -> list[str]:
    igs = _assignment_igs(meta)
    clusters: list[str] = []
    if igs & {58, 44, 42}:
        clusters.append("early flag/reload temps")
    if igs & {35, 56, 34}:
        clusters.append("late x594_b4/x594_b3 loop IV/tree-pointer swaps")
    if not clusters and igs:
        clusters.append("unclassified proof-assignment movement")
    return clusters


@search_app.command("delta-minimize")
def delta_minimize_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Target function to recombine and minimize.",
        ),
    ],
    left: Annotated[
        Path,
        typer.Option("--left", help="Left full translation-unit source file."),
    ],
    right: Annotated[
        Path,
        typer.Option("--right", help="Right full translation-unit source file."),
    ],
    out_dir: Annotated[
        Path,
        typer.Option(
            "--out-dir",
            help="Resumable artifact and result directory.",
        ),
    ] = Path("build/delta-minimize"),
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            min=1,
            help="Fail if the exact legal lattice exceeds this budget.",
        ),
    ] = 64,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target",
            help="Optional delta-minimize-color-target.v1 YAML file.",
        ),
    ] = None,
    donor: Annotated[
        Optional[list[str]],
        typer.Option(
            "--donor",
            help=(
                "Override color, objobjects, or stack-homes donor with "
                "AXIS=left|right; repeatable."
            ),
        ),
    ] = None,
    objobjects: Annotated[
        bool,
        typer.Option(
            "--objobjects/--no-objobjects",
            help="Collect ObjObject evidence for an exact four-axis result.",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic result JSON."),
    ] = False,
) -> None:
    """Exhaustively minimize the closed source-delta lattice between two parents."""

    try:
        donor_overrides = parse_donor_overrides(donor or ())
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--donor") from error

    melee_root = _compute_melee_root()
    resolved_left = _resolve_delta_source_file(left, melee_root=melee_root)
    resolved_right = _resolve_delta_source_file(right, melee_root=melee_root)
    cflags_from = _resolve_structure_source_file(
        function,
        None,
        melee_root=melee_root,
    )
    try:
        config = DeltaMinimizeConfig(
            function=function,
            left=resolved_left,
            right=resolved_right,
            out_dir=_resolve_delta_output_dir(out_dir, melee_root=melee_root),
            max_candidates=max_candidates,
            target_path=_resolve_delta_target_file(target),
            donor_overrides=donor_overrides,
            include_objobjects=objobjects,
            melee_root=melee_root,
            cflags_from=cflags_from,
        )
        result = run_delta_minimize(config)
    except DeltaMinimizeError as error:
        raise typer.BadParameter(_delta_error_message(error)) from error

    if json_out:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(render_delta_minimize_text(result))
    if result.status == "incomplete":
        raise typer.Exit(code=4)


@search_app.command("structure")
def structure_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to run structure search for."),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--source",
            help=(
                "Source file to use for source-based axes. When omitted, resolved from build/GALE01/report.json."
            ),
        ),
    ] = None,
    axes: Annotated[
        Optional[list[str]],
        typer.Option(
            "--axis",
            help=(
                "Structure axis to run; repeatable. Supported axes: "
                f"{', '.join(SUPPORTED_STRUCTURE_AXES)}. Defaults to "
                f"{', '.join(DEFAULT_STRUCTURE_AXES)}."
            ),
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help=(
                "Directory for generated candidates. Defaults to build/structure-search/<function>."
            ),
        ),
    ] = None,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Maximum ranked structure variants to return.",
        ),
    ] = 24,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-axis subprocess timeout in seconds.",
        ),
    ] = 120,
    score: Annotated[
        bool,
        typer.Option(
            "--score/--no-score",
            help="Compile and score retained candidate source variants.",
        ),
    ] = True,
    score_timeout: Annotated[
        float,
        typer.Option(
            "--score-timeout",
            help="Per-build/checkdiff scoring timeout in seconds.",
        ),
    ] = 120.0,
    pure_helpers: Annotated[
        Optional[list[str]],
        typer.Option(
            "--pure-helper",
            help=(
                "Treat a helper as read-only for source-lifetime probes. "
                "Use NAME or NAME=RETURN_TYPE; repeatable or comma-separated."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structure search payload as JSON."),
    ] = False,
) -> None:
    """Run structure-search axes and rank candidate variants."""
    melee_root = _compute_melee_root()
    resolved_source = _resolve_structure_source_file(
        function,
        source_file,
        melee_root=melee_root,
    )
    resolved_output_dir = _resolve_structure_output_dir(
        output_dir,
        function=function,
        melee_root=melee_root,
    )
    score_runner = None
    if score:

        def score_runner(variants):
            return score_structure_variants(
                melee_root=melee_root,
                function=function,
                source_path=resolved_source,
                variants=variants,
                timeout=score_timeout,
            )

    selected_axes = tuple(axes) if axes else DEFAULT_STRUCTURE_AXES
    baseline_classification = (
        _structure_baseline_classification(
            function=function,
            melee_root=melee_root,
            timeout=score_timeout,
        )
        if score and "inline-boundary" in selected_axes
        else None
    )
    payload = run_structure_search(
        function=function,
        source_path=resolved_source,
        output_dir=resolved_output_dir,
        axes=selected_axes,
        max_candidates=max_candidates,
        timeout=timeout,
        score_runner=score_runner,
        score_variants=score,
        baseline_classification=baseline_classification,
        read_only_helpers=_parse_structure_pure_helpers(pure_helpers),
    )
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(render_structure_text(payload))


def _structure_baseline_classification(
    *,
    function: str,
    melee_root: Path,
    timeout: float,
) -> dict | None:
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(melee_root / "tools" / "checkdiff.py"),
                function,
                "--format",
                "json",
                "--no-build",
                "--no-fingerprint",
            ],
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    classification = payload.get("classification")
    return classification if isinstance(classification, dict) else None


@search_app.command("plan-transforms")
def plan_transforms_cmd(
    function: Annotated[
        str, typer.Option("--function", "-f", help="Function to plan for.")
    ],
    unit: Annotated[
        str,
        typer.Option(
            "--unit", "-u", help="Translation unit path, e.g. melee/ft/ftcommon."
        ),
    ],
    force_phys: Annotated[
        str,
        typer.Option(
            "--force-phys",
            "--directed-force-phys",
            help=(
                "Force-phys proof vector as IG:PHYS or CLASS:IG:PHYS entries. "
                "Optional when --scheduler-order-target is provided."
            ),
        ),
    ] = "",
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--source",
            help="Optional C source file used to instantiate concrete probes.",
        ),
    ] = None,
    node_set_delta_path: Annotated[
        Optional[Path],
        typer.Option(
            "--node-set-delta",
            help="JSON node_set_delta payload from `debug solve coloring --json`.",
        ),
    ] = None,
    scheduler_order_target_path: Annotated[
        Optional[Path],
        typer.Option(
            "--scheduler-order-target",
            help="JSON scheduler-order target used to materialize source probes.",
        ),
    ] = None,
    select_order_json_path: Annotated[
        Optional[Path],
        typer.Option(
            "--select-order-json",
            help=(
                "JSON emitted by debug select-order-search --json, used to "
                "materialize retained Case-C window-order continuation probes."
            ),
        ),
    ] = None,
    coalesce_suggest_json_path: Annotated[
        Optional[Path],
        typer.Option(
            "--coalesce-suggest-json",
            help=(
                "JSON emitted by debug suggest coalesce --json, used to "
                "materialize retained GPR common-subexpr/coalesce source probes."
            ),
        ),
    ] = None,
    virtual_explain_json_path: Annotated[
        Optional[Path],
        typer.Option(
            "--virtual-explain-json",
            help=(
                "JSON emitted by debug inspect explain-virtual --json, used to "
                "derive retained Case-C blocker-color-chain repair goals."
            ),
        ),
    ] = None,
    current_owner_exhaustion_json_path: Annotated[
        Optional[Path],
        typer.Option(
            "--current-owner-exhaustion-json",
            help=(
                "Prior plan-transforms or allocator-ceiling JSON whose retained "
                "Case-C current source-owner terminal spans should seed "
                "alternate source-owner discovery."
            ),
        ),
    ] = None,
    max_per_family: Annotated[
        int,
        typer.Option(
            "--max-per-family", help="Maximum materialized probes per family."
        ),
    ] = 3,
    transform_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--transform-family",
            help=(
                "Restrict concrete probe materialization to one transform family. May be passed multiple times."
            ),
        ),
    ] = None,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes",
            help="Optional directory where materialized candidate source files are written.",
        ),
    ] = None,
    record_ledger: Annotated[
        bool,
        typer.Option(
            "--record-ledger/--no-record-ledger",
            help="Record the transform plan/probe outcome in the shared attempts ledger.",
        ),
    ] = False,
    validate_command: Annotated[
        Optional[str],
        typer.Option(
            "--validate-command",
            help=(
                "External command template to validate each generated probe. "
                "Use {candidate_path} as the candidate source placeholder."
            ),
        ),
    ] = None,
    stop_on_retained: Annotated[
        bool,
        typer.Option(
            "--stop-on-retained/--validate-all",
            help="Stop validation after the first retained source improvement.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Plan source-transform families and instantiate bounded probes."""
    import json as _json

    from src.search.directed.transform_corpus import (
        generate_transform_probe_report,
        plan_transform_experiments,
    )
    from src.mwcc_debug.diff_capture import function_pcdump_aliases
    from src.mwcc_debug.scheduler_order_realizer import parse_scheduler_order_target

    melee_root = _compute_melee_root()
    scheduler_order_target = None
    if scheduler_order_target_path is not None:
        try:
            scheduler_order_payload = _json.loads(
                scheduler_order_target_path.read_text(encoding="utf-8")
            )
            scheduler_order_target = parse_scheduler_order_target(
                scheduler_order_payload,
            )
        except OSError as exc:
            typer.echo(
                f"error: could not read --scheduler-order-target: {exc}", err=True
            )
            raise typer.Exit(2) from exc
        except (TypeError, ValueError, _json.JSONDecodeError) as exc:
            typer.echo(f"error: invalid --scheduler-order-target: {exc}", err=True)
            raise typer.Exit(2) from exc
        if scheduler_order_target.function != function:
            typer.echo(
                "error: --scheduler-order-target function "
                f"{scheduler_order_target.function!r} does not match --function {function!r}",
                err=True,
            )
            raise typer.Exit(2)
    try:
        if force_phys.strip():
            force_phys_map, force_class_id = _parse_directed_force_phys(force_phys)
        elif (
            scheduler_order_target is not None
            or function == "mnDiagram2_GetRankedFighter"
        ):
            force_phys_map = {}
            force_class_id = None
        else:
            raise ValueError("--directed-force-phys did not contain any entries")
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    node_set_delta = _load_node_set_delta(node_set_delta_path)
    try:
        window_order_continuation = _load_select_order_window_order_context(
            select_order_json_path,
        )
        coalesce_suggestion = _load_coalesce_suggest_context(
            coalesce_suggest_json_path,
        )
        virtual_explain_context = _load_virtual_explain_context(
            virtual_explain_json_path,
        )
        current_owner_exhaustion_context = _load_current_owner_exhaustion_context(
            current_owner_exhaustion_json_path,
        )
    except typer.BadParameter as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if virtual_explain_context is not None:
        payload_function = virtual_explain_context.get("function")
        if isinstance(payload_function, str) and payload_function != function:
            aliases = set(function_pcdump_aliases(function, melee_root))
            if payload_function not in aliases:
                typer.echo(
                    "error: --virtual-explain-json function "
                    f"{payload_function!r} does not match --function {function!r}",
                    err=True,
                )
                raise typer.Exit(2)
    requested_transform_families = transform_family
    if window_order_continuation is not None:
        requested_transform_families = list(transform_family or [])
        if not transform_family:
            for family_id in (
                RETAINED_GPR_CASE_C_WINDOW_ORDER_CONTINUATION_FAMILY_ID,
                RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
                RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID,
                RETAINED_GPR_CASE_C_SIMPLIFY_ORDER_CONTINUATION_FAMILY_ID,
                RETAINED_GPR_CASE_C_POST_SOURCE_OWNER_BACKTRACK_FAMILY_ID,
            ):
                if family_id not in requested_transform_families:
                    requested_transform_families.append(family_id)
    if coalesce_suggestion is not None:
        requested_transform_families = list(requested_transform_families or [])
        if (
            not transform_family
            and RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
            not in requested_transform_families
        ):
            requested_transform_families.append(
                RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID
            )
    if virtual_explain_context is not None:
        requested_transform_families = list(requested_transform_families or [])
        if not transform_family and not (
            RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
            in requested_transform_families
            or RETAINED_FPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
            in requested_transform_families
        ):
            requested_transform_families.append(
                RETAINED_GPR_CASE_C_TARGET_LIVE_RANGE_REPAIR_FAMILY_ID
            )
    if current_owner_exhaustion_context is not None:
        requested_transform_families = list(requested_transform_families or [])
        if (
            not transform_family
            and RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID
            not in requested_transform_families
        ):
            requested_transform_families.append(
                RETAINED_CASE_C_ALTERNATE_SOURCE_OWNER_FAMILY_ID
            )

    plan = plan_transform_experiments(
        function=function,
        unit=unit,
        force_phys=force_phys_map,
    )
    probes = ()
    report = None
    source_text = None
    source_path = _resolve_source_file(source_file, melee_root=melee_root)
    if source_path is None:
        source_path = _resolve_optional_plan_source_file(
            plan.source_file,
            melee_root=melee_root,
        )
    if source_path is not None:
        source_text = source_path.read_text()
    report = generate_transform_probe_report(
        source_text,
        function=function,
        unit=unit,
        force_phys=force_phys_map,
        force_class_id=force_class_id,
        function_aliases=function_pcdump_aliases(function, melee_root),
        families=requested_transform_families,
        max_per_family=max_per_family,
        node_set_delta=node_set_delta,
        scheduler_order_target=scheduler_order_target,
        window_order_continuation=window_order_continuation,
        coalesce_suggestion=coalesce_suggestion,
        virtual_explain_context=virtual_explain_context,
        current_owner_exhaustion_context=current_owner_exhaustion_context,
    )
    probes = report.probes

    payload = _transform_plan_payload(
        plan,
        probes,
        write_dir=write_probes,
        family_diagnostics=report.family_diagnostics,
        source_resolution=report.source_resolution,
    )
    node_set_summary = _node_set_delta_summary(
        node_set_delta,
        probes,
        source_text=source_text,
        function=function,
    )
    if node_set_summary is not None:
        payload["node_set_delta_summary"] = node_set_summary
        planning_summary = _node_set_delta_planning_summary(
            node_set_summary,
            probes,
            max_per_family=max_per_family,
        )
        if planning_summary is not None:
            payload["planning_summary"] = planning_summary
    if validate_command is not None:
        payload["validation"] = _run_transform_validations(
            payload["probes"],
            validate_command=validate_command,
            stop_on_retained=stop_on_retained,
        )
        payload["validation_summary"] = _summarize_transform_validations(
            payload["probes"],
            payload["validation"],
        )
    retained_window_summary = _retained_case_c_window_order_continuation_summary(
        payload["probes"],
        payload.get("validation"),
    )
    if retained_window_summary is not None:
        payload["retained_case_c_window_order_continuation_summary"] = (
            retained_window_summary
        )
        if isinstance(payload.get("validation_summary"), dict):
            payload["validation_summary"][
                "retained_case_c_window_order_continuation_summary"
            ] = retained_window_summary
    retained_post_source_owner_summary = (
        _retained_case_c_post_source_owner_backtrack_summary(
            payload["probes"],
            payload.get("validation"),
            payload.get("family_diagnostics"),
        )
    )
    if retained_post_source_owner_summary is not None:
        payload["retained_case_c_post_source_owner_backtrack_summary"] = (
            retained_post_source_owner_summary
        )
        if isinstance(payload.get("validation_summary"), dict):
            payload["validation_summary"][
                "retained_case_c_post_source_owner_backtrack_summary"
            ] = retained_post_source_owner_summary
            if retained_post_source_owner_summary.get("status") == "scored-exact":
                payload["validation_summary"]["stop_condition"] = (
                    "exact-post-source-owner-backtrack"
                )
            elif retained_post_source_owner_summary.get("status") in {
                "scored-negative",
                "terminal-blocked",
            }:
                blockers = payload["validation_summary"].setdefault(
                    "terminal_blockers",
                    [],
                )
                blocker = retained_post_source_owner_summary.get("terminal_blocker")
                if blocker and blocker not in blockers:
                    blockers.append(blocker)
    common_subexpr_coalesce_summary = (
        _retained_gpr_common_subexpr_coalesce_source_summary(
            payload["probes"],
            payload.get("validation"),
            payload.get("family_diagnostics"),
        )
    )
    if common_subexpr_coalesce_summary is not None:
        payload["retained_gpr_common_subexpr_coalesce_source_summary"] = (
            common_subexpr_coalesce_summary
        )
        if isinstance(payload.get("validation_summary"), dict):
            payload["validation_summary"][
                "retained_gpr_common_subexpr_coalesce_source_summary"
            ] = common_subexpr_coalesce_summary
            if common_subexpr_coalesce_summary.get("status") == "exact":
                payload["validation_summary"]["stop_condition"] = (
                    "exact-common-subexpr-coalesce-source"
                )
            elif common_subexpr_coalesce_summary.get("status") == "residual-hit":
                payload["validation_summary"]["stop_condition"] = (
                    "common-subexpr-coalesce-source-residual-hit"
                )
            blocker = common_subexpr_coalesce_summary.get("terminal_blocker")
            if blocker:
                blockers = payload["validation_summary"].setdefault(
                    "terminal_blockers",
                    [],
                )
                if blocker not in blockers:
                    blockers.append(blocker)
    retained_target_live_range_summary = (
        _retained_case_c_target_live_range_repair_summary(
            payload["probes"],
            payload.get("validation"),
            payload.get("family_diagnostics"),
        )
    )
    if retained_target_live_range_summary is not None:
        payload["retained_case_c_target_live_range_repair_summary"] = (
            retained_target_live_range_summary
        )
        if isinstance(payload.get("validation_summary"), dict):
            payload["validation_summary"][
                "retained_case_c_target_live_range_repair_summary"
            ] = retained_target_live_range_summary
            if retained_target_live_range_summary.get("status") == "exact":
                payload["validation_summary"]["stop_condition"] = (
                    "exact-retained-target-live-range-repair"
                )
            elif retained_target_live_range_summary.get("status") == "blocked":
                blocker = retained_target_live_range_summary.get("terminal_blocker")
                if blocker:
                    blockers = payload["validation_summary"].setdefault(
                        "terminal_blockers",
                        [],
                    )
                    if blocker not in blockers:
                        blockers.append(blocker)
    retained_simplify_order_summary = (
        _retained_case_c_simplify_order_continuation_summary(
            payload["probes"],
            payload.get("validation"),
        )
    )
    if retained_simplify_order_summary is not None:
        payload["retained_case_c_simplify_order_continuation_summary"] = (
            retained_simplify_order_summary
        )
        if isinstance(payload.get("validation_summary"), dict):
            payload["validation_summary"][
                "retained_case_c_simplify_order_continuation_summary"
            ] = retained_simplify_order_summary
    if record_ledger:
        payload["ledger_record"] = _record_transform_plan_attempt(
            function=function,
            plan=plan,
            probes=probes,
            source_path=source_path,
            validation_results=payload.get("validation"),
        )
    if json_out:
        typer.echo(_json.dumps(payload, indent=2))
        return

    typer.echo(f"Function: {plan.function}")
    typer.echo(f"Source:   {plan.source_file}")
    typer.echo("Clusters:")
    for cluster in plan.clusters:
        typer.echo(f"  - {cluster.label}: {', '.join(cluster.target_assignments)}")
        typer.echo(f"    families: {', '.join(cluster.family_ids)}")
    typer.echo("Families:")
    for family in plan.families:
        typer.echo(
            f"  - {family.family_id}: {family.label} (risk: {family.semantic_risk})"
        )
    typer.echo(f"Materialized probes: {len(payload['probes'])}")
    if payload.get("family_diagnostics"):
        typer.echo("Family diagnostics:")
        for item in payload["family_diagnostics"]:
            suffix = ""
            if item.get("no_probe_reason"):
                suffix = f" ({item['no_probe_reason']})"
            typer.echo(f"  - {item['family_id']}: {item['materialized_count']}{suffix}")
    if write_probes is not None:
        typer.echo(f"Probe directory: {write_probes}")
    if validate_command is not None:
        summary = payload.get("validation_summary", {})
        outcomes = summary.get("outcomes", {})
        typer.echo(
            "Validation: "
            + ", ".join(f"{key}={value}" for key, value in sorted(outcomes.items()))
        )
        if summary.get("stop_condition"):
            typer.echo(f"Stop condition: {summary['stop_condition']}")
    if record_ledger:
        record = payload["ledger_record"]
        typer.echo(
            f"Ledger: {record['outcome']} (attempt {record.get('attempt_index')})"
        )


@search_app.command("baseline-escape")
def baseline_escape_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to plan for."),
    ],
    source_function: Annotated[
        Optional[str],
        typer.Option(
            "--source-function",
            help="Function name to locate in the retained source if it differs.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--source",
            help="Optional retained C source baseline.",
        ),
    ] = None,
    allocator_ceiling_json: Annotated[
        Path,
        typer.Option(
            "--allocator-ceiling-json",
            help="Allocator-ceiling JSON with expression-scored terminal evidence.",
        ),
    ] = Path("allocator_ceiling.json"),
    expression_interferer_json: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-interferer-json",
            help="Expression-interferer repair JSON with post-bridge terminal.",
        ),
    ] = None,
    retained_frontiers_json: Annotated[
        Path,
        typer.Option(
            "--retained-frontiers-json",
            help="Retained-frontiers triage JSON proving known lanes exhausted.",
        ),
    ] = Path("retained_frontiers.json"),
    evidence_json: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--evidence-json",
            help="Supplemental evidence JSON for non-expression baseline escapes. Repeatable.",
        ),
    ] = None,
    score_json: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--score-json",
            help="Optional score JSON for generated candidates. Repeatable.",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option("--target", help="Target JSON for validation hints."),
    ] = None,
    cflags_from: Annotated[
        Optional[Path],
        typer.Option("--cflags-from", help="Source path for score-source cflags."),
    ] = None,
    unit_source: Annotated[
        Optional[Path],
        typer.Option("--unit-source", help="Unit source path for validation hints."),
    ] = None,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help="Baseline pcdump used to enable expression scoring.",
        ),
    ] = None,
    expression_source: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-source",
            help="Source file used for expression attribution.",
        ),
    ] = None,
    max_candidates: Annotated[
        int,
        typer.Option("--max-candidates", help="Maximum candidates to emit."),
    ] = 12,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes",
            help="Optional directory where candidate source files are written.",
        ),
    ] = None,
    include_source: Annotated[
        bool,
        typer.Option(
            "--include-source/--no-include-source",
            help="Include candidate source text in JSON output.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit machine-readable JSON."),
    ] = True,
) -> None:
    """Generate post-ceiling baseline escape candidates for retained allocator stalls."""
    from src.mwcc_debug.post_ceiling_baseline_escape import (
        generate_baseline_escape_candidate_files,
        generate_baseline_escape_candidates,
        load_json_file,
        resolve_baseline_source_path,
    )

    def resolve_input(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def path_option(path: Path | None) -> str | None:
        if path is None:
            return None
        return str(resolve_input(path))

    melee_root = _compute_melee_root()
    try:
        allocator_payload = load_json_file(resolve_input(allocator_ceiling_json))
        expression_payload = (
            load_json_file(resolve_input(expression_interferer_json))
            if expression_interferer_json is not None
            else None
        )
        retained_payload = load_json_file(resolve_input(retained_frontiers_json))
        supplemental_payloads = [
            load_json_file(resolve_input(path)) for path in (evidence_json or [])
        ]
        if target is not None and resolve_input(target).is_file():
            supplemental_payloads.append(load_json_file(resolve_input(target)))
        score_payloads = [
            load_json_file(resolve_input(path)) for path in (score_json or [])
        ]
        resolved_source = resolve_baseline_source_path(
            repo_root=melee_root,
            function=function,
            source_file=source_file,
            allocator_ceiling=allocator_payload,
            expression_interferer=expression_payload,
            retained_frontiers=retained_payload,
            supplemental_evidence=supplemental_payloads,
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if resolved_source is None:
        payload = {
            "status": "blocked",
            "kind": "post-ceiling-baseline-escape",
            "function": function,
            "source_function": source_function or function,
            "reason": "source-file-not-resolved",
        }
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Function: {function}")
            typer.echo("Status:   blocked")
            typer.echo("Reason: source-file-not-resolved")
        raise typer.Exit(3)

    try:
        source_text = resolved_source.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    validation_options = {
        "function": function,
        "source_function": source_function or function,
        "target": path_option(target),
        "cflags_from": path_option(cflags_from),
        "unit_source": path_option(unit_source),
        "expression_baseline": path_option(expression_baseline),
        "expression_source": path_option(expression_source) or str(resolved_source),
    }
    if write_probes is not None:
        output_dir = write_probes.expanduser()
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        payload = generate_baseline_escape_candidate_files(
            source_text,
            function=function,
            source_function=source_function,
            allocator_ceiling=allocator_payload,
            expression_interferer=expression_payload,
            retained_frontiers=retained_payload,
            supplemental_evidence=supplemental_payloads,
            score_payloads=score_payloads,
            output_dir=output_dir.resolve(),
            max_candidates=max_candidates,
            include_source=include_source,
            validation_options=validation_options,
        )
    else:
        payload = generate_baseline_escape_candidates(
            source_text,
            function=function,
            source_function=source_function,
            allocator_ceiling=allocator_payload,
            expression_interferer=expression_payload,
            retained_frontiers=retained_payload,
            supplemental_evidence=supplemental_payloads,
            score_payloads=score_payloads,
            max_candidates=max_candidates,
            include_source=include_source,
            validation_options=validation_options,
        )
    payload["source_file"] = str(resolved_source)

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Function: {payload.get('function')}")
        typer.echo(f"Status:   {payload.get('status')}")
        typer.echo(f"Source:   {resolved_source}")
        typer.echo(f"Candidates: {len(payload.get('candidates') or [])}")
        if payload.get("terminal_summary"):
            terminal = payload["terminal_summary"]
            typer.echo(f"Terminal: {terminal.get('terminal_reason')}")
        elif payload.get("reason"):
            typer.echo(f"Reason: {payload['reason']}")

    if payload.get("status") in {"blocked", "terminal"}:
        raise typer.Exit(3)


@search_app.command("source-model-synthesis")
def source_model_synthesis_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f", help="Function to synthesize source families for."
        ),
    ],
    meta_ceiling_json: Annotated[
        Path,
        typer.Option(
            "--meta-ceiling-json",
            help="Meta-ceiling JSON or retained-frontiers aggregate JSON.",
        ),
    ],
    retained_frontiers_json: Annotated[
        Optional[Path],
        typer.Option(
            "--retained-frontiers-json",
            help="Optional retained-frontiers aggregate to merge with the meta ceiling.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option("--source-file", "--source", help="Retained C source baseline."),
    ] = None,
    source_function: Annotated[
        Optional[str],
        typer.Option(
            "--source-function",
            help="Retained source function name. Defaults to the profiled source alias.",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option("--target", help="Target JSON for score-source validation."),
    ] = None,
    cflags_from: Annotated[
        Path,
        typer.Option("--cflags-from", help="Source path for score-source cflags."),
    ] = Path("src/melee/mn/mndiagram.c"),
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help="Baseline pcdump for expression-aware score-source validation.",
        ),
    ] = None,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes", help="Directory for generated candidate .c files."
        ),
    ] = None,
    max_per_dimension: Annotated[
        int,
        typer.Option("--max-per-dimension", help="Maximum candidates per dimension."),
    ] = 5,
    score: Annotated[
        bool,
        typer.Option(
            "--score/--no-score", help="Run debug target score-source for probes."
        ),
    ] = False,
    score_json: Annotated[
        Optional[list[Path]],
        typer.Option("--score-json", help="Offline score-source JSON. Repeatable."),
    ] = None,
    checkdiff_guard: Annotated[
        bool,
        typer.Option(
            "--checkdiff-guard/--no-checkdiff-guard",
            help="Require score-source structural guard validation.",
        ),
    ] = True,
    remote: Annotated[
        bool,
        typer.Option("--remote/--no-remote", help="Forward --remote to score-source."),
    ] = False,
    remote_fallback: Annotated[
        bool,
        typer.Option(
            "--remote-fallback/--no-remote-fallback",
            help="Forward --remote-fallback to score-source.",
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="score-source timeout in seconds."),
    ] = 120.0,
    include_source: Annotated[
        bool,
        typer.Option(
            "--include-source/--no-include-source",
            help="Include generated source text in JSON output.",
        ),
    ] = False,
    continue_after_final_source_family: Annotated[
        bool,
        typer.Option(
            "--continue-after-final-source-family/--no-continue-after-final-source-family",
            help=(
                "Opt in to bounded source-family probes after terminal Sort "
                "proofs that are not automatically routed."
            ),
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit machine-readable JSON."),
    ] = True,
) -> None:
    """Generate and classify post-meta-ceiling source-family probes."""
    from dataclasses import replace

    from src.mwcc_debug.post_meta_source_family_synthesis import (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION,
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY,
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL,
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        SourceFamilySynthesisError,
        build_generated_source_family_payload,
        classify_source_family_scores,
        generate_source_family_candidates,
        load_json_file,
        materialize_semantic_recombine_source_candidates,
        normalize_meta_ceiling_context,
        resolve_source_function_context,
        score_source_candidates,
        terminalize_semantic_recombine_materialization_failure,
        temporary_probe_dir,
        write_source_family_candidates,
        _recursive_strings,
    )

    def stack_clean_recovery_source_retained(raw: object) -> str | None:
        if isinstance(raw, Mapping):
            post_stack = raw.get("post_stack_clean_no_anchor_evidence")
            if isinstance(post_stack, Mapping):
                for key in ("retained_scored_probes", "ranked_post_stack_clean_probes"):
                    for row in post_stack.get(key) or []:
                        if not isinstance(row, Mapping):
                            continue
                        source_retained = row.get("source_retained")
                        if isinstance(source_retained, str) and source_retained:
                            return source_retained
            evidence = raw.get("stack_clean_no_anchor_evidence")
            if isinstance(evidence, Mapping):
                source_retained = evidence.get("source_retained")
                if isinstance(source_retained, str) and source_retained:
                    return source_retained
            for value in raw.values():
                found = stack_clean_recovery_source_retained(value)
                if found is not None:
                    return found
        if isinstance(raw, list):
            for value in raw:
                found = stack_clean_recovery_source_retained(value)
                if found is not None:
                    return found
        return None

    def resolve_input(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def resolve_output(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def path_for_metadata(path: Path | None) -> str | None:
        if path is None:
            return None
        expanded = path.expanduser()
        return str(expanded if expanded.is_absolute() else path)

    melee_root = _compute_melee_root()
    input_paths = [resolve_input(meta_ceiling_json)]
    if retained_frontiers_json is not None:
        input_paths.append(resolve_input(retained_frontiers_json))
    try:
        payloads = [load_json_file(path) for path in input_paths]
        context = normalize_meta_ceiling_context(
            payloads,
            function=function,
            repo_root=melee_root,
            input_artifacts=input_paths,
        )
        if source_function is not None:
            context = replace(context, source_function=source_function)
        default_source_file = source_file
        next_models = {
            str(value)
            for value in (
                context.next_unsupported_source_model,
                *(
                    raw
                    for raw in _recursive_strings(context.current_ceiling)
                    if raw == DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
                ),
            )
            if value
        }
        next_families = {
            str(value)
            for value in (
                context.next_unsupported_source_family,
                *(
                    raw
                    for raw in _recursive_strings(context.current_ceiling)
                    if raw == DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
                ),
            )
            if value
        }
        if (
            default_source_file is None
            and (
                context.next_unsupported_source_dimension
                in {
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                    DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION,
                    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
                }
                or DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
                in next_models
                or DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
                in next_families
            )
        ):
            retained_source = stack_clean_recovery_source_retained(
                context.current_ceiling
            )
            if retained_source is not None:
                default_source_file = Path(retained_source)
        resolved_source = _resolve_source_file(
            default_source_file or Path(context.source_file),
            melee_root=melee_root,
        )
        assert resolved_source is not None
        source_text = resolved_source.read_text(encoding="utf-8")
        context = resolve_source_function_context(source_text, context)
        validation_options = {
            "target": path_for_metadata(target),
            "cflags_from": path_for_metadata(cflags_from),
            "expression_source": str(resolved_source),
            "expression_baseline": path_for_metadata(expression_baseline),
            "checkdiff_guard": checkdiff_guard,
        }
        needs_source = bool(write_probes or score or include_source)
        candidates = generate_source_family_candidates(
            source_text,
            context,
            max_per_dimension=max_per_dimension,
            include_source=needs_source,
            validation_options=validation_options,
            continue_after_final_source_family=continue_after_final_source_family,
        )
        output_dir: Path | None = None
        if write_probes is not None:
            output_dir = resolve_output(write_probes)
            candidates = write_source_family_candidates(
                candidates,
                output_dir,
                source_text,
                include_source=include_source,
            )
        score_payloads = [
            load_json_file(resolve_input(path)) for path in (score_json or [])
        ]
        score_mode = "offline" if score_payloads else "none"
        if score_payloads and score:
            score = False
        if score:
            if target is None:
                raise SourceFamilySynthesisError(
                    "target-required",
                    "--target is required with --score",
                )
            if output_dir is None:
                output_dir = temporary_probe_dir(melee_root)
                candidates = write_source_family_candidates(
                    candidates,
                    output_dir,
                    source_text,
                    include_source=include_source,
                )
            score_payloads = score_source_candidates(
                candidates,
                repo_root=melee_root,
                context=context,
                target=resolve_input(target),
                cflags_from=resolve_input(cflags_from),
                expression_source=resolved_source,
                expression_baseline=(
                    resolve_input(expression_baseline)
                    if expression_baseline is not None
                    else None
                ),
                checkdiff_guard=checkdiff_guard,
                remote=remote,
                remote_fallback=remote_fallback,
                timeout=timeout,
            )
            score_mode = "live"
    except SourceFamilySynthesisError as exc:
        payload = {"status": "blocked", "reason": exc.code, "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Status: blocked\nReason: {exc.code}\n{exc}", err=True)
        raise typer.Exit(2) from exc
    except OSError as exc:
        payload = {"status": "blocked", "reason": "io-error", "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if score_payloads:
        payload = classify_source_family_scores(
            candidates,
            score_payloads,
            context,
            continue_after_final_source_family=continue_after_final_source_family,
        )
        semantic_recombine = payload.get("semantic_recombine")
        if (
            score_mode == "live"
            and payload.get("status") in {"terminal", "blocked"}
            and isinstance(semantic_recombine, Mapping)
            and semantic_recombine.get("status") == "actionable"
            and payload.get("partial_score") is None
        ):
            materialization = materialize_semantic_recombine_source_candidates(
                payload,
                source_text,
                context,
                validation_options=validation_options,
                max_candidates=max_per_dimension,
                include_source=True,
            )
            recombine_candidates = list(materialization.get("candidates") or [])
            existing_ids = {str(row.get("candidate_id")) for row in candidates}
            recombine_candidates = [
                row
                for row in recombine_candidates
                if str(row.get("candidate_id")) not in existing_ids
            ]
            if recombine_candidates:
                if output_dir is None:
                    output_dir = temporary_probe_dir(melee_root)
                recombine_candidates = write_source_family_candidates(
                    recombine_candidates,
                    output_dir,
                    source_text,
                    include_source=include_source,
                )
                recombine_score_payloads = score_source_candidates(
                    recombine_candidates,
                    repo_root=melee_root,
                    context=context,
                    target=resolve_input(target),
                    cflags_from=resolve_input(cflags_from),
                    expression_source=resolved_source,
                    expression_baseline=(
                        resolve_input(expression_baseline)
                        if expression_baseline is not None
                        else None
                    ),
                    checkdiff_guard=checkdiff_guard,
                    remote=remote,
                    remote_fallback=remote_fallback,
                    timeout=timeout,
                )
                candidates = [*candidates, *recombine_candidates]
                score_payloads = [*score_payloads, *recombine_score_payloads]
                payload = classify_source_family_scores(
                    candidates,
                    score_payloads,
                    context,
                    continue_after_final_source_family=(
                        continue_after_final_source_family
                    ),
                )
                payload["semantic_recombine_second_pass"] = {
                    "status": "scored",
                    "materialization": {
                        **dict(materialization),
                        "candidates": recombine_candidates,
                    },
                    "candidate_count": len(recombine_candidates),
                    "score_count": len(recombine_score_payloads),
                    "candidate_ids": [
                        str(row.get("candidate_id")) for row in recombine_candidates
                    ],
                }
            else:
                payload = terminalize_semantic_recombine_materialization_failure(
                    payload,
                    context,
                    materialization,
                )
                payload["semantic_recombine_second_pass"] = {
                    "status": "materialization-blocked",
                    "materialization": dict(materialization),
                    "candidate_count": 0,
                    "score_count": 0,
                }
        payload["score_mode"] = (
            "live-partial" if payload.get("partial_score") is not None else score_mode
        )
        payload["context"] = context.to_dict()
        payload["candidates"] = candidates
    else:
        payload = build_generated_source_family_payload(
            candidates,
            context,
            continue_after_final_source_family=continue_after_final_source_family,
        )
        payload["score_mode"] = score_mode
    payload["source_file"] = str(resolved_source)
    if output_dir is not None:
        payload["output_dir"] = str(output_dir)

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Function: {payload.get('function')}")
        typer.echo(f"Status:   {payload.get('status')}")
        typer.echo(f"Candidates: {payload.get('candidate_count')}")
        if payload.get("status") == "terminal":
            typer.echo(f"Terminal: {payload.get('terminal_reason')}")
        elif payload.get("status") in {"blocked", "incomplete"}:
            typer.echo(f"Reason: {payload.get('reason')}")

    interruption = payload.get("interruption")
    if isinstance(interruption, Mapping) and interruption.get("exit_code") is not None:
        raise typer.Exit(int(interruption["exit_code"]))
    if payload.get("status") == "terminal":
        raise typer.Exit(3)
    if payload.get("status") in {"blocked", "incomplete"}:
        raise typer.Exit(3)


@search_app.command("post-source-context-next-dimension")
def post_source_context_next_dimension_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to discover from."),
    ],
    source_model_json: Annotated[
        Optional[Path],
        typer.Option(
            "--source-model-json",
            help="Terminal source-model-synthesis JSON.",
        ),
    ] = None,
    retained_frontiers_json: Annotated[
        Optional[Path],
        typer.Option(
            "--retained-frontiers-json",
            help="Retained-frontiers aggregate JSON from the exhausted source context.",
        ),
    ] = None,
    allocator_ceiling_json: Annotated[
        Optional[Path],
        typer.Option(
            "--allocator-ceiling-json",
            help="Allocator-ceiling JSON consuming the exhausted retained frontiers.",
        ),
    ] = None,
    continuation_json: Annotated[
        Optional[Path],
        typer.Option(
            "--continuation-json",
            help="Optional source-family-continuation JSON.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option("--source-file", "--source", help="Retained source file."),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="Optional path to write discovery JSON."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit machine-readable JSON."),
    ] = True,
) -> None:
    """Discover the next explicit handoff after Draw source-context exhaustion."""
    from src.mwcc_debug.post_source_context_discovery import (
        PostSourceContextDiscoveryError,
        PostSourceContextFprCeilingNextDimensionDiscovery,
        load_json_file,
    )

    def resolve_input(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def resolve_output(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    try:
        payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
            function=function,
            source_model=(
                load_json_file(resolve_input(source_model_json))
                if source_model_json is not None
                else None
            ),
            retained_frontiers=(
                load_json_file(resolve_input(retained_frontiers_json))
                if retained_frontiers_json is not None
                else None
            ),
            allocator_ceiling=(
                load_json_file(resolve_input(allocator_ceiling_json))
                if allocator_ceiling_json is not None
                else None
            ),
            continuation=(
                load_json_file(resolve_input(continuation_json))
                if continuation_json is not None
                else None
            ),
            source_file=(
                str(_resolve_source_file(source_file, melee_root=_compute_melee_root()))
                if source_file is not None
                else None
            ),
        )
    except (OSError, PostSourceContextDiscoveryError) as exc:
        payload = {"status": "blocked", "reason": "input-error", "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Status: blocked\nReason: input-error\n{exc}", err=True)
        raise typer.Exit(2) from exc

    if out is not None:
        out_path = resolve_output(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Function: {payload.get('function')}")
        typer.echo(f"Status:   {payload.get('status')}")
        if payload.get("status") == "unsupported-source-dimension":
            typer.echo(f"Dimension: {payload.get('next_unsupported_source_dimension')}")
        elif payload.get("status") == "unsupported-source-family":
            typer.echo(f"Family: {payload.get('next_unsupported_source_family')}")
            unsupported = payload.get("unsupported_source_expression_class")
            if isinstance(unsupported, str) and unsupported:
                typer.echo(f"Expression class: {unsupported}")
        elif payload.get("status") == "source-actionable":
            typer.echo(
                f"Ranked retained C probes: {len(payload.get('ranked_retained_c_probes') or [])}"
            )
        elif payload.get("reason"):
            typer.echo(f"Reason:   {payload.get('reason')}")

    if payload.get("status") == "source-actionable":
        return
    if payload.get("status") in {
        "unsupported-source-dimension",
        "unsupported-source-family",
    }:
        raise typer.Exit(3)
    raise typer.Exit(2)


@search_app.command("post-source-ceiling-axis")
def post_source_ceiling_axis_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to discover from."),
    ],
    source_model_json: Annotated[
        Optional[Path],
        typer.Option(
            "--source-model-json",
            help="Terminal source-model-synthesis JSON.",
        ),
    ] = None,
    retained_frontiers_json: Annotated[
        Optional[Path],
        typer.Option(
            "--retained-frontiers-json",
            help="Retained-frontiers aggregate JSON from source ceiling triage.",
        ),
    ] = None,
    allocator_ceiling_json: Annotated[
        Optional[Path],
        typer.Option(
            "--allocator-ceiling-json",
            help="Allocator-ceiling JSON for the exhausted retained frontiers.",
        ),
    ] = None,
    post_source_context_json: Annotated[
        Optional[Path],
        typer.Option(
            "--post-source-context-json",
            help="Optional Draw post-source-context next-dimension JSON.",
        ),
    ] = None,
    continuation_json: Annotated[
        Optional[Path],
        typer.Option(
            "--continuation-json",
            help="Optional source-family-continuation JSON.",
        ),
    ] = None,
    first_divergence_json: Annotated[
        Optional[Path],
        typer.Option(
            "--first-divergence-json",
            help="Optional first-divergence JSON for post-axis repair attribution.",
        ),
    ] = None,
    simplify_order_json: Annotated[
        Optional[Path],
        typer.Option(
            "--simplify-order-json",
            help="Optional retained simplify-order JSON for terminal repair evidence.",
        ),
    ] = None,
    bank: Annotated[
        str,
        typer.Option("--bank", help="Register bank to use: auto, gpr, or fpr."),
    ] = "auto",
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="Optional path to write discovery JSON."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit machine-readable JSON."),
    ] = True,
) -> None:
    """Rank backend/codegen axes after terminal source-family exhaustion."""
    from src.mwcc_debug.post_source_ceiling_axis import (
        PostSourceCeilingAxisDiscovery,
        PostSourceCeilingAxisError,
        load_json_file,
        render_text,
    )

    def resolve_input(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def resolve_output(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    try:
        payload = PostSourceCeilingAxisDiscovery().discover(
            function=function,
            source_model=(
                load_json_file(resolve_input(source_model_json))
                if source_model_json is not None
                else None
            ),
            retained_frontiers=(
                load_json_file(resolve_input(retained_frontiers_json))
                if retained_frontiers_json is not None
                else None
            ),
            allocator_ceiling=(
                load_json_file(resolve_input(allocator_ceiling_json))
                if allocator_ceiling_json is not None
                else None
            ),
            post_source_context=(
                load_json_file(resolve_input(post_source_context_json))
                if post_source_context_json is not None
                else None
            ),
            continuation=(
                load_json_file(resolve_input(continuation_json))
                if continuation_json is not None
                else None
            ),
            first_divergence=(
                load_json_file(resolve_input(first_divergence_json))
                if first_divergence_json is not None
                else None
            ),
            simplify_order=(
                load_json_file(resolve_input(simplify_order_json))
                if simplify_order_json is not None
                else None
            ),
            bank=bank,
        )
    except (OSError, PostSourceCeilingAxisError) as exc:
        payload = {"status": "blocked", "reason": "input-error", "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Status: blocked\nReason: input-error\n{exc}", err=True)
        raise typer.Exit(2) from exc

    if out is not None:
        out_path = resolve_output(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(render_text(payload))

    if payload.get("status") == "source-actionable":
        return
    if payload.get("status") == "terminal":
        raise typer.Exit(3)
    raise typer.Exit(2)


@search_app.command("source-family-continuation")
def source_family_continuation_cmd(
    source_model_json: Annotated[
        Path,
        typer.Option(
            "--source-model-json",
            "--classified-json",
            help="Classified source-model-synthesis JSON.",
        ),
    ],
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Expected function for guard checking."),
    ] = None,
    artifacts: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--artifact",
            help="Continuation artifact JSON such as combine/reconcile/focus output.",
        ),
    ] = None,
    score_json: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--score-json",
            help="Raw score-source JSON to include as continuation evidence.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="Optional path to write the continuation JSON."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit machine-readable JSON."),
    ] = True,
) -> None:
    """Summarize post-meta source-family continuation evidence."""
    from src.mwcc_debug.post_meta_source_family_synthesis import (
        SourceFamilySynthesisError,
        build_source_family_continuation_payload,
        load_json_file,
    )

    def resolve_input(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    def resolve_output(path: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return expanded.resolve()

    try:
        source_model_path = resolve_input(source_model_json)
        classified = load_json_file(source_model_path)
        if isinstance(classified, dict):
            classified.setdefault("_artifact_path", str(source_model_path))
        if function is not None and classified.get("function") != function:
            raise SourceFamilySynthesisError(
                "function-mismatch",
                (
                    f"source model JSON is for {classified.get('function')}, not {function}"
                ),
            )
        continuation_artifacts = [
            load_json_file(resolve_input(path))
            for path in [*(artifacts or []), *(score_json or [])]
        ]
        payload = build_source_family_continuation_payload(
            classified,
            continuation_artifacts,
        )
    except SourceFamilySynthesisError as exc:
        payload = {"status": "blocked", "reason": exc.code, "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Status: blocked\nReason: {exc.code}\n{exc}", err=True)
        raise typer.Exit(2) from exc
    except OSError as exc:
        payload = {"status": "blocked", "reason": "io-error", "message": str(exc)}
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if out is not None:
        out_path = resolve_output(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["artifact"] = str(out_path)

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Function: {payload.get('function')}")
        typer.echo(f"Status:   {payload.get('status')}")
        typer.echo(f"Family:   {payload.get('family_id')}")
        if payload.get("terminal"):
            typer.echo(f"Terminal: {payload.get('terminal_reason')}")
        elif payload.get("accepted_candidates"):
            typer.echo(f"Accepted: {len(payload.get('accepted_candidates') or [])}")

    if payload.get("status") in {"blocked", "incomplete"}:
        raise typer.Exit(3)


def _classify_source_delta(removed: list[str], added: list[str]) -> str:
    text = "\n".join([*removed, *added])
    lowered = text.lower()
    if any(token in lowered for token in ("x594", "_b4", "_b3", "flag")):
        return "field-bit/predicate-shape"
    if re.search(r"\b(for|while|do)\b|\+\+|--", text):
        return "loop-control-shape"
    if re.search(r"\bif\b|\?|&&|\|\|", text):
        return "predicate-shape"
    if re.search(r"\b(?:int|s32|u32|float|bool|BOOL)\s+\w+", text):
        return "decl-lifetime-shape"
    if re.search(r"\b(?:return|break|continue|goto)\b", text):
        return "control-flow-shape"
    return "source-shape"


def _source_deltas(base_text: str, candidate_text: str) -> list[dict]:
    base_lines = base_text.splitlines()
    candidate_lines = candidate_text.splitlines()
    matcher = difflib.SequenceMatcher(None, base_lines, candidate_lines)
    deltas: list[dict] = []
    for idx, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes(), 1):
        if tag == "equal":
            continue
        removed = base_lines[i1:i2]
        added = candidate_lines[j1:j2]
        deltas.append(
            {
                "hunk": idx,
                "tag": tag,
                "base_lines": [i1 + 1, i2],
                "candidate_lines": [j1 + 1, j2],
                "kind": _classify_source_delta(removed, added),
                "removed": removed[:8],
                "added": added[:8],
                "removed_count": len(removed),
                "added_count": len(added),
            }
        )
    return deltas


def _source_hunks(
    base_text: str,
    candidate_text: str,
    *,
    candidate_id: str,
) -> list[dict]:
    base_lines = base_text.splitlines()
    candidate_lines = candidate_text.splitlines()
    matcher = difflib.SequenceMatcher(None, base_lines, candidate_lines)
    hunks: list[dict] = []
    for idx, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes(), 1):
        if tag == "equal":
            continue
        removed = base_lines[i1:i2]
        added = candidate_lines[j1:j2]
        hunks.append(
            {
                "candidate_id": candidate_id,
                "hunk": idx,
                "tag": tag,
                "base_start": i1,
                "base_end": i2,
                "candidate_start": j1,
                "candidate_end": j2,
                "kind": _classify_source_delta(removed, added),
                "removed": removed,
                "added": added,
            }
        )
    return hunks


_MANUAL_RANGE_RE = re.compile(
    r"^(?P<candidate>[^:=]+):"
    r"(?P<base_start>\d+)-(?P<base_end>\d+)="
    r"(?P<candidate_start>\d+)-(?P<candidate_end>\d+)$"
)


def _parse_manual_range(raw: str) -> dict:
    match = _MANUAL_RANGE_RE.match(raw.strip())
    if match is None:
        raise typer.BadParameter(
            "--range must look like CANDIDATE_ID:BASE_START-BASE_END=CANDIDATE_START-CANDIDATE_END"
        )
    values = match.groupdict()
    out = {
        "candidate_id": values["candidate"].strip(),
        "base_start": int(values["base_start"]),
        "base_end": int(values["base_end"]),
        "candidate_start": int(values["candidate_start"]),
        "candidate_end": int(values["candidate_end"]),
    }
    if not out["candidate_id"]:
        raise typer.BadParameter("--range candidate id cannot be empty")
    for key in ("base_start", "base_end", "candidate_start", "candidate_end"):
        if out[key] < 1:
            raise typer.BadParameter(f"--range {key} must be >= 1")
    if out["base_end"] < out["base_start"] - 1:
        raise typer.BadParameter("--range base end must be >= base start - 1")
    if out["candidate_end"] < out["candidate_start"] - 1:
        raise typer.BadParameter("--range candidate end must be >= candidate start - 1")
    return out


def _manual_source_hunks(
    *,
    base_text: str,
    candidate_text: str,
    candidate_id: str,
    manual_ranges: list[dict],
) -> list[dict]:
    base_lines = base_text.splitlines()
    candidate_lines = candidate_text.splitlines()
    hunks: list[dict] = []
    for idx, spec in enumerate(manual_ranges, 1):
        if spec["candidate_id"] != candidate_id:
            continue
        base_start = int(spec["base_start"]) - 1
        base_end = int(spec["base_end"])
        candidate_start = int(spec["candidate_start"]) - 1
        candidate_end = int(spec["candidate_end"])
        if base_end > len(base_lines):
            raise typer.BadParameter(
                f"--range for {candidate_id} references base line {base_end}, but base has {len(base_lines)} line(s)"
            )
        if candidate_end > len(candidate_lines):
            raise typer.BadParameter(
                f"--range for {candidate_id} references candidate line "
                f"{candidate_end}, but candidate has {len(candidate_lines)} line(s)"
            )
        removed = base_lines[base_start:base_end]
        added = candidate_lines[candidate_start:candidate_end]
        hunks.append(
            {
                "candidate_id": candidate_id,
                "hunk": idx,
                "tag": "manual",
                "base_start": base_start,
                "base_end": base_end,
                "candidate_start": candidate_start,
                "candidate_end": candidate_end,
                "kind": "manual-subhunk",
                "removed": removed,
                "added": added,
            }
        )
    return hunks


def _hunks_overlap(left: dict, right: dict) -> bool:
    left_start = int(left["base_start"])
    left_end = int(left["base_end"])
    right_start = int(right["base_start"])
    right_end = int(right["base_end"])
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    return max(left_start, right_start) < min(left_end, right_end)


def _merge_source_hunks(base_text: str, hunks: list[dict]) -> str | None:
    base_lines = base_text.splitlines()
    ordered = sorted(
        hunks,
        key=lambda hunk: (int(hunk["base_start"]), int(hunk["base_end"])),
    )
    for idx, current in enumerate(ordered):
        for other in ordered[idx + 1 :]:
            if _hunks_overlap(current, other):
                return None
    merged: list[str] = []
    cursor = 0
    for hunk in ordered:
        start = int(hunk["base_start"])
        end = int(hunk["base_end"])
        if start < cursor:
            return None
        merged.extend(base_lines[cursor:start])
        merged.extend(hunk["added"])
        cursor = end
    merged.extend(base_lines[cursor:])
    return "\n".join(merged) + ("\n" if base_text.endswith("\n") else "")


_SIMPLE_DECL_RE = re.compile(
    r"^\s*(?P<type>(?:const\s+)?(?:(?:unsigned|signed)\s+)?"
    r"(?:char|short|int|long|float|double|bool|BOOL|"
    r"s8|u8|s16|u16|s32|u32|s64|u64|f32|f64|"
    r"struct\s+[A-Za-z_]\w+|[A-Za-z_]\w+))"
    r"(?:\s*\*+\s*|\s+)(?P<name>[A-Za-z_]\w*)(?:\s*=\s*[^;]+)?;\s*$"
)
_SIMPLE_BIND_RE = re.compile(
    r"^\s*(?P<target>[A-Za-z_]\w*)\s*=\s*(?P<source>[A-Za-z_]\w*)\s*;\s*$"
)
_SIMPLE_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.*);\s*$"
)
_IDENT_TOKEN_RE = re.compile(r"[A-Za-z_]\w*")


def _is_simple_declaration_line(line: str) -> bool:
    return _SIMPLE_DECL_RE.match(line) is not None


def _simple_declaration_name(line: str) -> str | None:
    match = _SIMPLE_DECL_RE.match(line)
    if match is None:
        return None
    type_name = match.group("type").strip()
    type_name = re.sub(r"^(?:const\s+)?(?:(?:unsigned|signed)\s+)?", "", type_name)
    known_types = {
        "char",
        "short",
        "int",
        "long",
        "float",
        "double",
        "bool",
        "BOOL",
        "s8",
        "u8",
        "s16",
        "u16",
        "s32",
        "u32",
        "s64",
        "u64",
        "f32",
        "f64",
    }
    if type_name not in known_types and not type_name.startswith("struct "):
        return None
    return match.group("name")


def _record_declaration_line(declarations: dict[str, str], line: str) -> bool:
    name = _simple_declaration_name(line)
    if name is None:
        return False
    previous = declarations.get(name)
    if previous is not None and previous != line:
        return False
    declarations[name] = line
    return True


def _simple_binding_assignment(line: str) -> tuple[str, str] | None:
    match = _SIMPLE_BIND_RE.match(line)
    if match is None:
        return None
    return match.group("target"), match.group("source")


def _parse_simple_assignment(line: str) -> dict | None:
    match = _SIMPLE_ASSIGN_RE.match(line)
    if match is None:
        return None
    return match.groupdict()


def _identifier_is_standalone_value(expr: str, start: int, end: int) -> bool:
    prev = start - 1
    while prev >= 0 and expr[prev].isspace():
        prev -= 1
    if prev >= 0 and expr[prev] == ".":
        return False
    if prev >= 0 and expr[prev] == ">" and prev - 1 >= 0 and expr[prev - 1] == "-":
        return False

    next_idx = end
    while next_idx < len(expr) and expr[next_idx].isspace():
        next_idx += 1
    if next_idx < len(expr) and expr[next_idx] == "(":
        return False
    return True


def _expression_tokens(expr: str) -> list[tuple[bool, str]]:
    tokens: list[tuple[bool, str]] = []
    cursor = 0
    for match in _IDENT_TOKEN_RE.finditer(expr):
        if match.start() > cursor:
            tokens.append((False, expr[cursor : match.start()]))
        tokens.append(
            (
                _identifier_is_standalone_value(expr, match.start(), match.end()),
                match.group(0),
            )
        )
        cursor = match.end()
    if cursor < len(expr):
        tokens.append((False, expr[cursor:]))
    return tokens


def _infer_assignment_substitutions(
    *,
    base_line: str,
    rewritten_line: str,
) -> dict[str, str] | None:
    base = _parse_simple_assignment(base_line)
    rewritten = _parse_simple_assignment(rewritten_line)
    if base is None or rewritten is None:
        return None
    if rewritten["lhs"] != base["lhs"]:
        return None

    base_tokens = _expression_tokens(base["rhs"])
    rewritten_tokens = _expression_tokens(rewritten["rhs"])
    if len(base_tokens) != len(rewritten_tokens):
        return None

    observed: dict[str, set[str]] = {}
    for (base_is_ident, base_token), (rewritten_is_ident, rewritten_token) in zip(
        base_tokens,
        rewritten_tokens,
    ):
        if base_is_ident != rewritten_is_ident:
            return None
        if not base_is_ident:
            if base_token != rewritten_token:
                return None
            continue
        observed.setdefault(base_token, set()).add(rewritten_token)
        if len(observed[base_token]) > 1:
            return None

    return {
        source: next(iter(targets))
        for source, targets in observed.items()
        if next(iter(targets)) != source
    }


def _compose_assignment_with_substitutions(
    base_line: str,
    substitutions: dict[str, str],
) -> str | None:
    base = _parse_simple_assignment(base_line)
    if base is None:
        return None
    tokens = _expression_tokens(base["rhs"])
    rhs = "".join(
        substitutions.get(token, token) if is_ident else token
        for is_ident, token in tokens
    )
    return f"{base['indent']}{base['lhs']} = {rhs};"


def _unique_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _merge_compatible_replacement_group(group: list[dict]) -> dict | None:
    first = group[0]
    removed = list(first["removed"])
    if not removed or any(list(hunk["removed"]) != removed for hunk in group):
        return None
    if len(removed) != 1:
        return None
    base_assignment = _parse_simple_assignment(removed[0])
    if base_assignment is None:
        return None

    prefix_lines: list[str] = []
    substitutions: dict[str, str] = {}
    binding_sources: dict[str, str] = {}
    declarations: dict[str, str] = {}
    for hunk in group:
        rewritten_lines = [
            line
            for line in hunk["added"]
            if (
                (parsed := _parse_simple_assignment(line)) is not None
                and parsed["lhs"] == base_assignment["lhs"]
            )
        ]
        if len(rewritten_lines) != 1:
            return None

        inferred = _infer_assignment_substitutions(
            base_line=removed[0],
            rewritten_line=rewritten_lines[0],
        )
        if inferred is None:
            return None

        hunk_bindings: dict[str, str] = {}
        hunk_declarations: set[str] = set()
        for line in hunk["added"]:
            if line == rewritten_lines[0]:
                continue
            declaration_name = _simple_declaration_name(line)
            if declaration_name is not None:
                if not _record_declaration_line(declarations, line):
                    return None
                hunk_declarations.add(declaration_name)
                prefix_lines.append(line)
                continue
            binding = _simple_binding_assignment(line)
            if binding is None:
                return None
            target, source = binding
            if target in hunk_bindings and hunk_bindings[target] != source:
                return None
            hunk_bindings[target] = source
            prefix_lines.append(line)

        if any(name not in hunk_bindings for name in hunk_declarations):
            return None

        for source, target in inferred.items():
            if source in substitutions and substitutions[source] != target:
                return None
            substitutions[source] = target
            if hunk_bindings.get(target) != source:
                return None
            if target in binding_sources and binding_sources[target] != source:
                return None
            binding_sources[target] = source

    reverse: dict[str, str] = {}
    for source, target in substitutions.items():
        if target in reverse and reverse[target] != source:
            return None
        reverse[target] = source

    composed = _compose_assignment_with_substitutions(removed[0], substitutions)
    if composed is None:
        return None
    merged = dict(first)
    merged["candidate_id"] = "+".join(hunk["candidate_id"] for hunk in group)
    merged["hunk"] = min(int(hunk["hunk"]) for hunk in group)
    merged["added"] = [*_unique_lines(prefix_lines), composed]
    return merged


def _normalize_compatible_overlap_hunks(hunks: list[dict]) -> list[dict] | None:
    for idx, current in enumerate(hunks):
        for other in hunks[idx + 1 :]:
            if not _hunks_overlap(current, other):
                continue
            if int(current["base_start"]) != int(other["base_start"]) or int(
                current["base_end"]
            ) != int(other["base_end"]):
                return None

    groups: dict[tuple[int, int], list[dict]] = {}
    ordered_keys: list[tuple[int, int]] = []
    for hunk in hunks:
        key = (int(hunk["base_start"]), int(hunk["base_end"]))
        if key not in groups:
            ordered_keys.append(key)
            groups[key] = []
        groups[key].append(hunk)

    normalized: list[dict] = []
    for key in ordered_keys:
        group = groups[key]
        if len(group) == 1:
            normalized.append(group[0])
            continue
        start, end = key
        if start == end:
            if any(hunk["removed"] for hunk in group):
                return None
            added = [line for hunk in group for line in hunk["added"]]
            if not added or any(
                not _is_simple_declaration_line(line) for line in added
            ):
                return None
            declarations: dict[str, str] = {}
            if any(not _record_declaration_line(declarations, line) for line in added):
                return None
            merged = dict(group[0])
            merged["candidate_id"] = "+".join(hunk["candidate_id"] for hunk in group)
            merged["hunk"] = min(int(hunk["hunk"]) for hunk in group)
            merged["added"] = _unique_lines(added)
            normalized.append(merged)
            continue

        merged_replacement = _merge_compatible_replacement_group(group)
        if merged_replacement is None:
            return None
        normalized.append(merged_replacement)

    return normalized


def _merge_combine_source_hunks(
    base_text: str, hunks: list[dict]
) -> tuple[str, str] | None:
    merged = _merge_source_hunks(base_text, hunks)
    if merged is not None:
        return merged, "non-overlap"

    normalized = _normalize_compatible_overlap_hunks(hunks)
    if normalized is None:
        return None
    merged = _merge_source_hunks(base_text, normalized)
    if merged is None:
        return None
    return merged, "compatible-overlap"


def _generated_artifacts(candidate_text: str) -> list[str]:
    artifacts: list[str] = []
    if re.search(r"(?m)^\s*#\s*line\b", candidate_text):
        artifacts.append("preprocessor-line-marker")
    if re.search(r"\b(?:var|tmp|sp|phi)_?\d+\b", candidate_text):
        artifacts.append("generated-temp-name")
    if re.search(
        r"\bgoto\b|^\s*[A-Za-z_]\w*:\s*$",
        candidate_text,
        flags=re.MULTILINE,
    ):
        artifacts.append("unnatural-goto-label")
    if re.search(r"\bvolatile\b", candidate_text):
        artifacts.append("volatile-marker")
    return artifacts


def _naturalization_suggestions(
    *,
    deltas: list[dict],
    artifacts: list[str],
    clusters: list[str],
) -> list[str]:
    suggestions: list[str] = []
    if "preprocessor-line-marker" in artifacts:
        suggestions.append("Drop preprocessor line markers before retaining the edit.")
    if "generated-temp-name" in artifacts:
        suggestions.append(
            "Rename generated temporaries to source-meaningful locals and keep "
            "only the lifetime/definition movement they caused."
        )
    if "unnatural-goto-label" in artifacts:
        suggestions.append(
            "Remove generated control-flow scaffolding; naturalize it as a structured if/loop shape before re-scoring."
        )
    kinds = {delta["kind"] for delta in deltas}
    if "field-bit/predicate-shape" in kinds:
        suggestions.append(
            "Minimize field-bit/predicate changes to the smallest readable "
            "reload, flag, or direct-test variant that preserves assignment "
            "movement."
        )
    if "loop-control-shape" in kinds:
        suggestions.append(
            "Minimize loop-control changes separately from pointer/field "
            "changes, then re-score the combined naturalized edit."
        )
    if any("early flag/reload" in cluster for cluster in clusters):
        suggestions.append(
            "Treat early flag/reload edits as one cluster; single-temp probes may lose the allocator movement."
        )
    if any("late x594" in cluster for cluster in clusters):
        suggestions.append(
            "Treat late x594 and loop/tree-pointer edits as one cluster before judging byte-score recovery."
        )
    if not suggestions:
        suggestions.append(
            "No generated artifacts detected; try retaining the smallest hunk "
            "that preserves the reported proof-assignment movement."
        )
    return suggestions


def _run_triage_score_command(
    template: str | None,
    *,
    candidate_path: Path,
) -> dict | None:
    if not template:
        return None
    args = [
        token.replace("{candidate}", str(candidate_path)).replace(
            "{candidate_path}", str(candidate_path)
        )
        for token in shlex.split(template)
    ]
    if not any(str(candidate_path) in token for token in args):
        args.append(str(candidate_path))
    proc = subprocess.run(args, capture_output=True, text=True)
    result: dict = {
        "command": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    try:
        result["parsed_json"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    return result


_SCORE_RESULT_HANDOFF_KEYS = (
    "score",
    "pcdump_path",
    "target_score",
    "structural_guard",
    "structural_guard_error",
    "unsafe_local_pcdump_lane",
)


def _score_result_handoff_fields(score_result: dict | None) -> dict:
    parsed = (score_result or {}).get("parsed_json")
    if not isinstance(parsed, dict):
        return {}
    return {key: parsed[key] for key in _SCORE_RESULT_HANDOFF_KEYS if key in parsed}


def _combine_score_source_command_hint(
    *,
    candidate_path: Path,
    parsed: dict,
) -> str:
    function = parsed.get("function")
    target = parsed.get("target") or parsed.get("target_spec")
    command = [
        "melee-agent",
        "debug",
        "target",
        "score-source",
        str(candidate_path),
        "--function",
        function if isinstance(function, str) and function else "<function>",
        "--target",
        target if isinstance(target, str) and target else "<target-spec.json>",
        "--json",
        "--retain-pcdump",
    ]
    cflags_from = parsed.get("cflags_from") or parsed.get("cflags_unit")
    if isinstance(cflags_from, str) and cflags_from:
        command.extend(["--cflags-from", cflags_from])
    return shlex.join(command)


def _combine_score_handoff(
    *,
    candidate_path: Path,
    score_result: dict | None,
    handoff_fields: dict,
) -> dict | None:
    parsed = (score_result or {}).get("parsed_json")
    if not isinstance(parsed, dict):
        return None
    handoff: dict = {
        "kind": "score-retained-source",
        "status": "available",
        "source_retained": str(candidate_path),
        "score_command": _combine_score_source_command_hint(
            candidate_path=candidate_path,
            parsed=parsed,
        ),
        "requires_function": not isinstance(parsed.get("function"), str),
        "requires_target_spec": not (
            isinstance(parsed.get("target"), str)
            or isinstance(parsed.get("target_spec"), str)
        ),
    }
    pcdump_path = handoff_fields.get("pcdump_path")
    if isinstance(pcdump_path, str):
        handoff["pcdump_path"] = pcdump_path
    unsafe_lane = handoff_fields.get("unsafe_local_pcdump_lane")
    if isinstance(unsafe_lane, dict):
        handoff["status"] = "blocked"
        handoff["terminal_blocker"] = "unsafe-local-pcdump-lane"
        handoff["unsafe_local_pcdump_lane"] = unsafe_lane
    return handoff


def _triage_candidate(
    *,
    candidate_id: str,
    candidate_path: Path,
    base_text: str,
    telemetry: list[dict],
    score_command: str | None,
) -> dict:
    candidate_text = candidate_path.read_text()
    source_hash = _source_hash(candidate_text)
    meta = _triage_telemetry_for(
        telemetry,
        candidate_id=candidate_id,
        source_hash=source_hash,
    )
    deltas = _source_deltas(base_text, candidate_text)
    artifacts = _generated_artifacts(candidate_text)
    clusters = _assignment_clusters(meta)
    return {
        "candidate_id": candidate_id,
        "path": str(candidate_path),
        "source_hash": source_hash,
        "byte_score": None if meta is None else meta.get("byte_score"),
        "directed_score": (
            None
            if meta is None
            else meta.get("directed_scalar", meta.get("displacement"))
        ),
        "assignment_progress": _assignment_progress(meta),
        "assignment_clusters": clusters,
        "source_deltas": deltas,
        "generated_artifacts": artifacts,
        "naturalization_suggestions": _naturalization_suggestions(
            deltas=deltas,
            artifacts=artifacts,
            clusters=clusters,
        ),
        "score_result": _run_triage_score_command(
            score_command,
            candidate_path=candidate_path,
        ),
    }


def _combined_assignment_progress(metas: list[dict | None]) -> dict:
    buckets: dict[str, dict[tuple[int, int | None], str]] = {
        "satisfied": {},
        "blocked": {},
        "abstained": {},
    }
    for meta in metas:
        progress = _assignment_progress(meta)
        proof = (meta or {}).get("proof_assignments") or {}
        for status in ("satisfied", "blocked", "abstained"):
            entries = proof.get(status, []) or []
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                try:
                    original = int(entry["original_ig"])
                except (KeyError, TypeError, ValueError):
                    continue
                desired_raw = entry.get("desired_phys")
                try:
                    desired = int(desired_raw) if desired_raw is not None else None
                except (TypeError, ValueError):
                    desired = None
                rendered = (
                    progress[status][index]
                    if index < len(progress[status])
                    else _format_assignment(entry, status=status)
                )
                buckets[status][(original, desired)] = rendered
    return {
        status: [
            rendered
            for _key, rendered in sorted(values.items(), key=lambda item: item[0])
        ]
        for status, values in buckets.items()
    }


def _combined_clusters(metas: list[dict | None]) -> list[str]:
    clusters: list[str] = []
    for meta in metas:
        for cluster in _assignment_clusters(meta):
            if cluster not in clusters:
                clusters.append(cluster)
    return clusters


def _combination_attribution(clusters: list[str], parents: list[str]) -> str:
    if len(clusters) > 1:
        return "multi-cluster interaction"
    if len(parents) > 1:
        return "same-cluster crossover"
    return "single-candidate"


def _combined_candidate_id(parent_ids: list[str], text: str) -> str:
    parent_part = "-".join(parent_ids)
    return f"combine-{parent_part}-{_source_hash(text)[:10]}"


def _load_combine_candidate(
    *,
    spec: str,
    base_text: str,
    telemetry: list[dict],
    manual_ranges: list[dict] | None = None,
) -> dict:
    candidate_id, path = _parse_triage_candidate(spec)
    text = path.read_text()
    source_hash = _source_hash(text)
    meta = _triage_telemetry_for(
        telemetry,
        candidate_id=candidate_id,
        source_hash=source_hash,
    )
    manual_hunks = _manual_source_hunks(
        base_text=base_text,
        candidate_text=text,
        candidate_id=candidate_id,
        manual_ranges=manual_ranges or [],
    )
    return {
        "candidate_id": candidate_id,
        "path": path,
        "source_hash": source_hash,
        "meta": meta,
        "hunks": manual_hunks
        or _source_hunks(
            base_text,
            text,
            candidate_id=candidate_id,
        ),
    }


def _hunk_summary(hunk: dict) -> dict:
    return {
        "parent": hunk["candidate_id"],
        "kind": hunk["kind"],
        "base_lines": [
            int(hunk["base_start"]) + 1,
            int(hunk["base_end"]),
        ],
    }


def _structural_boundary_token(line: str) -> str | None:
    stripped = line.strip()
    stripped = re.sub(r"^(?:/\*[^*]*\*/\s*)+", "", stripped)
    return stripped if stripped in {"{", "}"} else None


def _is_structural_boundary_line(line: str) -> bool:
    return _structural_boundary_token(line) is not None


def _manual_hunk_structural_diagnostics(hunks: list[dict]) -> list[dict]:
    diagnostics: list[dict] = []
    for hunk in hunks:
        if hunk.get("kind") != "manual-subhunk":
            continue
        added_structural = {
            token
            for line in hunk.get("added", [])
            if (token := _structural_boundary_token(line)) is not None
        }
        for line in hunk.get("removed", []):
            token = _structural_boundary_token(line)
            if token is None or token in added_structural:
                continue
            diagnostics.append(
                {
                    "kind": "manual-range-crosses-structural-boundary",
                    "hunk": _hunk_summary(hunk),
                    "removed": [line],
                    "message": (
                        "Manual subhunk removes a brace/control boundary without preserving it in the candidate range."
                    ),
                }
            )
    return diagnostics


def _brace_balance_diagnostics(merged_text: str, hunks: list[dict]) -> list[dict]:
    balance = 0
    for line_no, line in enumerate(merged_text.splitlines(), 1):
        for char in line:
            if char == "{":
                balance += 1
            elif char == "}":
                balance -= 1
            if balance < 0:
                return [
                    {
                        "kind": "unbalanced-braces",
                        "line": line_no,
                        "message": "Merged source closes more braces than it opens.",
                        "applied_hunks": [_hunk_summary(hunk) for hunk in hunks],
                    }
                ]
    if balance == 0:
        return []
    return [
        {
            "kind": "unbalanced-braces",
            "brace_balance": balance,
            "message": "Merged source has unmatched opening braces.",
            "applied_hunks": [_hunk_summary(hunk) for hunk in hunks],
        }
    ]


def _duplicate_declaration_diagnostics(
    merged_text: str,
    hunks: list[dict],
) -> list[dict]:
    declarations: dict[tuple[int, str], int] = {}
    diagnostics: list[dict] = []
    scope_stack = [0]
    next_scope_id = 1
    for line_no, line in enumerate(merged_text.splitlines(), 1):
        stripped = line.strip()
        leading_closes = len(stripped) - len(stripped.lstrip("}"))
        for _ in range(leading_closes):
            if len(scope_stack) > 1:
                scope_stack.pop()
        name = _simple_declaration_name(line)
        if name is not None:
            key = (scope_stack[-1], name)
            previous = declarations.get(key)
            if previous is not None:
                diagnostics.append(
                    {
                        "kind": "duplicate-local-declaration",
                        "name": name,
                        "line": line_no,
                        "previous_line": previous,
                        "message": (
                            f"Merged source declares {name!r} more than once in the same brace scope."
                        ),
                        "applied_hunks": [_hunk_summary(hunk) for hunk in hunks],
                    }
                )
            else:
                declarations[key] = line_no
        for char in stripped[leading_closes:]:
            if char == "{":
                scope_stack.append(next_scope_id)
                next_scope_id += 1
            elif char == "}" and len(scope_stack) > 1:
                scope_stack.pop()
    return diagnostics


def _manual_combine_source_diagnostics(
    *,
    merged_text: str,
    hunks: list[dict],
) -> list[dict]:
    if not any(hunk.get("kind") == "manual-subhunk" for hunk in hunks):
        return []
    diagnostics = _manual_hunk_structural_diagnostics(hunks)
    diagnostics.extend(_brace_balance_diagnostics(merged_text, hunks))
    diagnostics.extend(_duplicate_declaration_diagnostics(merged_text, hunks))
    return diagnostics


def _combine_candidate_pair(
    *,
    base_text: str,
    out_dir: Path,
    left: dict,
    right: dict,
    score_command: str | None,
) -> dict:
    parents = [left["candidate_id"], right["candidate_id"]]
    hunks = [*left["hunks"], *right["hunks"]]
    clusters = _combined_clusters([left["meta"], right["meta"]])
    merge_result = _merge_combine_source_hunks(base_text, hunks)
    if merge_result is None:
        return {
            "parents": parents,
            "status": "skipped",
            "reason": "overlapping-source-hunks",
            "clusters": clusters,
            "attribution": _combination_attribution(clusters, parents),
        }
    merged_text, merge_strategy = merge_result
    validation_diagnostics = _manual_combine_source_diagnostics(
        merged_text=merged_text,
        hunks=hunks,
    )
    if validation_diagnostics:
        return {
            "parents": parents,
            "status": "skipped",
            "reason": "invalid-manual-subhunk-source",
            "validation_diagnostics": validation_diagnostics,
            "applied_hunks": [_hunk_summary(hunk) for hunk in hunks],
            "clusters": clusters,
            "attribution": _combination_attribution(clusters, parents),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = _combined_candidate_id(parents, merged_text)
    out_path = out_dir / f"{candidate_id}.c"
    out_path.write_text(merged_text)
    score_result = _run_triage_score_command(
        score_command,
        candidate_path=out_path,
    )
    handoff_fields = _score_result_handoff_fields(score_result)
    result = {
        "candidate_id": candidate_id,
        "parents": parents,
        "status": "ok",
        "merge_strategy": merge_strategy,
        "path": str(out_path),
        "source_hash": _source_hash(merged_text),
        "applied_hunks": [_hunk_summary(hunk) for hunk in hunks],
        "assignment_union": _combined_assignment_progress(
            [left["meta"], right["meta"]]
        ),
        "clusters": clusters,
        "attribution": _combination_attribution(clusters, parents),
        "score_result": score_result,
    }
    result.update(handoff_fields)
    continuation = _combine_score_handoff(
        candidate_path=out_path,
        score_result=score_result,
        handoff_fields=handoff_fields,
    )
    if continuation is not None:
        result["continuation"] = continuation
    return result


def _combine_manual_range_span(start: int, end: int) -> tuple[int, int]:
    if end <= start:
        return start + 1, end
    return start + 1, end


def _combine_hunk_span(hunk: dict) -> dict:
    base_start, base_end = _combine_manual_range_span(
        int(hunk["base_start"]),
        int(hunk["base_end"]),
    )
    candidate_start, candidate_end = _combine_manual_range_span(
        int(hunk["candidate_start"]),
        int(hunk["candidate_end"]),
    )
    return {
        "hunk": int(hunk["hunk"]),
        "kind": hunk["kind"],
        "base_start": base_start,
        "base_end": base_end,
        "candidate_start": candidate_start,
        "candidate_end": candidate_end,
    }


def _combine_invalid_manual_terminal_summary(combos: list[dict]) -> dict | None:
    if not combos:
        return None
    if any(
        combo.get("status") != "skipped"
        or combo.get("reason") != "invalid-manual-subhunk-source"
        for combo in combos
    ):
        return None
    return {
        "status": "blocked",
        "dominant_blocker": "manual-subhunk-range-invalid",
        "terminal_blocker": "incompatible-manual-subhunk-range",
        "skipped_count": len(combos),
        "skipped_parent_pairs": [list(combo.get("parents", [])) for combo in combos],
        "validation_diagnostics": [
            {
                "parents": list(combo.get("parents", [])),
                "diagnostics": combo.get("validation_diagnostics", []),
            }
            for combo in combos
        ],
        "next_actions": [
            {
                "kind": "manual-subhunk-range-repair",
                "guidance": (
                    "Adjust --range values so zero-width insertions use "
                    "BASE_START-(BASE_START-1), and avoid ranges that remove "
                    "braces or duplicate declarations."
                ),
            }
        ],
    }


def _combine_overlap_terminal_summary(
    combos: list[dict],
    loaded: list[dict],
) -> dict | None:
    if not combos:
        return None
    if any(
        combo.get("status") != "skipped"
        or combo.get("reason") != "overlapping-source-hunks"
        for combo in combos
    ):
        return None
    candidate_hint = " ".join(
        "--candidate " + shlex.quote(f"{item['candidate_id']}={item['path']}")
        for item in loaded
    )
    range_hint = (
        "--range CANDIDATE_ID:BASE_START-BASE_END=CANDIDATE_START-CANDIDATE_END"
    )
    command_hint = f"melee-agent debug search combine --base <base> {candidate_hint} {range_hint} --json"

    return {
        "status": "blocked",
        "dominant_blocker": "recombine-overlapping-source-hunks",
        "terminal_blocker": "manual-subhunk-recombine-required",
        "skipped_count": len(combos),
        "skipped_parent_pairs": [list(combo.get("parents", [])) for combo in combos],
        "parent_hunk_spans": [
            {
                "candidate_id": item["candidate_id"],
                "path": str(item["path"]),
                "hunk_spans": [_combine_hunk_span(hunk) for hunk in item["hunks"]],
            }
            for item in loaded
        ],
        "manual_range_hint": (
            "Retry debug search combine with --range "
            "CANDIDATE_ID:BASE_START-BASE_END=CANDIDATE_START-CANDIDATE_END "
            "using parent_hunk_spans to split overlapping broad hunks."
        ),
        "next_actions": [
            {
                "kind": "manual-subhunk-recombine",
                "command_hint": command_hint,
            }
        ],
    }


def _combine_terminal_summary(combos: list[dict], loaded: list[dict]) -> dict | None:
    return _combine_invalid_manual_terminal_summary(
        combos
    ) or _combine_overlap_terminal_summary(combos, loaded)


def _meta_to_dict(meta) -> dict:
    if is_dataclass(meta):
        return asdict(meta)
    return dict(meta)


def _parse_assignment_spec(raw: str) -> tuple[int, int]:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) != 2:
        raise typer.BadParameter("assignment spec must look like IG:PHYS, e.g. 42:3")
    try:
        return (
            _parse_directed_int(parts[0], prefix="ig"),
            _parse_directed_phys(parts[1]),
        )
    except ValueError as exc:
        raise typer.BadParameter(f"invalid assignment spec {raw!r}: {exc}") from exc


def _assignment_keys_from_score(score_result: dict | None) -> set[tuple[int, int]]:
    if not score_result:
        return set()
    parsed = score_result.get("parsed_json")
    if not isinstance(parsed, dict):
        return set()
    proof = parsed.get("proof_assignments") or {}
    if not isinstance(proof, dict):
        return set()
    keys: set[tuple[int, int]] = set()
    for entry in proof.get("satisfied", []) or []:
        if isinstance(entry, str):
            match = re.match(r"ig(?P<ig>\d+)->r(?P<phys>\d+)$", entry.strip())
            if match:
                keys.add((int(match.group("ig")), int(match.group("phys"))))
            continue
        if not isinstance(entry, dict):
            continue
        try:
            keys.add((int(entry["original_ig"]), int(entry["desired_phys"])))
        except (KeyError, TypeError, ValueError):
            continue
    target_score = parsed.get("target_score")
    virtuals = target_score.get("virtuals") if isinstance(target_score, dict) else None
    if isinstance(virtuals, dict):
        for raw_ig, virtual in virtuals.items():
            if not isinstance(virtual, dict):
                continue
            try:
                ig = _parse_directed_int(str(raw_ig), prefix="ig")
                expected = int(virtual["expected"])
            except (KeyError, TypeError, ValueError):
                continue
            actual = virtual.get("actual")
            matched = virtual.get("matched")
            if matched is None:
                matched = virtual.get("hit")
            if matched is True:
                keys.add((ig, expected))
                continue
            try:
                if actual is not None and int(actual) == expected:
                    keys.add((ig, expected))
            except (TypeError, ValueError):
                continue
    return keys


def _score_parsed_json(score_result: dict | None) -> dict | None:
    parsed = (score_result or {}).get("parsed_json")
    return parsed if isinstance(parsed, dict) else None


def _score_number(value) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _score_normalized_diff_lines(score_result: dict | None) -> int | float | None:
    parsed = _score_parsed_json(score_result)
    if parsed is None:
        return None
    guard = parsed.get("structural_guard")
    if isinstance(guard, dict):
        value = _score_number(guard.get("normalized_diff_lines"))
        if value is not None:
            return value
    return _score_number(parsed.get("normalized_diff_lines"))


def _score_target_total(score_result: dict | None) -> int | float | None:
    parsed = _score_parsed_json(score_result)
    target_score = parsed.get("target_score") if isinstance(parsed, dict) else None
    if not isinstance(target_score, dict):
        return None
    return _score_number(target_score.get("total"))


def _protected_assignment_map(assignments: set[tuple[int, int]]) -> dict[str, int]:
    return {str(ig): phys for ig, phys in sorted(assignments)}


def _protected_assignment_list(assignments: set[tuple[int, int]]) -> list[dict]:
    return [{"ig": ig, "phys": phys} for ig, phys in sorted(assignments)]


def _combine_protected_candidate_summary(
    combo: dict,
    *,
    required_assignments: set[tuple[int, int]],
) -> dict:
    score_result = combo.get("score_result")
    parsed = _score_parsed_json(score_result)
    normalized_diff_lines = _score_normalized_diff_lines(score_result)
    satisfied = _assignment_keys_from_score(score_result)
    protected_hit = required_assignments & satisfied
    missing = required_assignments - satisfied
    score_returncode = (
        score_result.get("returncode") if isinstance(score_result, dict) else None
    )
    structural_guard = (
        parsed.get("structural_guard") if isinstance(parsed, dict) else None
    )
    evaluable = (
        combo.get("status") == "ok"
        and score_returncode == 0
        and parsed is not None
        and isinstance(structural_guard, dict)
        and normalized_diff_lines is not None
    )
    summary = {
        "candidate_id": combo.get("candidate_id")
        or "+".join(str(parent) for parent in combo.get("parents", [])),
        "parents": list(combo.get("parents", [])),
        "status": combo.get("status"),
        "path": combo.get("path"),
        "evaluable": evaluable,
        "score_returncode": score_returncode,
        "protected_assignments_satisfied": not missing,
        "protected_preserved_count": len(protected_hit),
        "protected_count": len(required_assignments),
        "satisfied_protected_assignments": _protected_assignment_list(protected_hit),
        "missing_protected_assignments": _protected_assignment_list(missing),
        "normalized_diff_lines": normalized_diff_lines,
        "target_score_total": _score_target_total(score_result),
    }
    if isinstance(structural_guard, dict):
        summary["structural_guard"] = {
            key: structural_guard[key]
            for key in (
                "accepted",
                "normalized_diff_lines",
                "opcode_similarity",
                "frame_delta",
            )
            if key in structural_guard
        }
    if not evaluable:
        if score_result is None:
            summary["unevaluable_reason"] = "missing-score-command"
        elif score_returncode != 0:
            summary["unevaluable_reason"] = "score-command-failed"
        elif parsed is None:
            summary["unevaluable_reason"] = "score-json-missing"
        elif not isinstance(structural_guard, dict):
            summary["unevaluable_reason"] = "structural-guard-missing"
        elif normalized_diff_lines is None:
            summary["unevaluable_reason"] = "normalized-diff-lines-missing"
    return summary


def _combine_protected_candidate_sort_key(candidate: dict) -> tuple:
    normalized = candidate.get("normalized_diff_lines")
    normalized_sort = (
        normalized if isinstance(normalized, (int, float)) else float("inf")
    )
    target_total = candidate.get("target_score_total")
    target_sort = (
        target_total if isinstance(target_total, (int, float)) else float("inf")
    )
    missing_count = len(candidate.get("missing_protected_assignments") or [])
    return (
        0 if candidate.get("protected_assignments_satisfied") else 1,
        normalized_sort,
        missing_count,
        target_sort,
        str(candidate.get("candidate_id") or ""),
    )


def _combine_protected_skipped_pairs(combos: list[dict]) -> list[dict]:
    return [
        {
            "parents": list(combo.get("parents", [])),
            "reason": combo.get("reason"),
            "validation_diagnostics": combo.get("validation_diagnostics", []),
        }
        for combo in combos
        if combo.get("status") == "skipped"
    ]


def _combine_protected_structural_synthesis_summary(
    combos: list[dict],
    *,
    required_assignments: set[tuple[int, int]],
    max_normalized_diff_lines: int | None,
    source_components: list[str],
) -> dict:
    ok_combos = [combo for combo in combos if combo.get("status") == "ok"]
    candidates = [
        _combine_protected_candidate_summary(
            combo,
            required_assignments=required_assignments,
        )
        for combo in ok_combos
    ]
    ranked_candidates = sorted(candidates, key=_combine_protected_candidate_sort_key)
    evaluable_candidates = [
        candidate for candidate in ranked_candidates if candidate.get("evaluable")
    ]
    unevaluable_candidates = [
        candidate for candidate in ranked_candidates if not candidate.get("evaluable")
    ]
    skipped_pairs = _combine_protected_skipped_pairs(combos)

    def within_target(candidate: dict) -> bool:
        normalized = candidate.get("normalized_diff_lines")
        if not isinstance(normalized, (int, float)):
            return False
        return (
            max_normalized_diff_lines is None or normalized <= max_normalized_diff_lines
        )

    preserving_candidates = [
        candidate
        for candidate in evaluable_candidates
        if candidate.get("protected_assignments_satisfied")
    ]
    found_candidates = [
        candidate for candidate in preserving_candidates if within_target(candidate)
    ]
    lower_drift_lost = [
        candidate
        for candidate in evaluable_candidates
        if (
            not candidate.get("protected_assignments_satisfied")
            and within_target(candidate)
        )
    ]
    lower_drift_lost.sort(
        key=lambda item: (
            item.get("normalized_diff_lines")
            if isinstance(item.get("normalized_diff_lines"), (int, float))
            else float("inf"),
            str(item.get("candidate_id") or ""),
        )
    )
    terminal_blockers: list[str] = []
    if lower_drift_lost:
        terminal_blockers.append("lower-drift-candidates-lost-protected-assignments")
    if any(
        candidate.get("normalized_diff_lines") is not None
        and not within_target(candidate)
        for candidate in preserving_candidates
    ):
        terminal_blockers.append("preserving-candidates-did-not-beat-structural-target")
    skipped_reasons = {
        str(pair.get("reason"))
        for pair in skipped_pairs
        if pair.get("reason") is not None
    }
    if "overlapping-source-hunks" in skipped_reasons:
        terminal_blockers.append("recombine-overlapping-source-hunks")
    if "invalid-manual-subhunk-source" in skipped_reasons:
        terminal_blockers.append("invalid-manual-subhunk-source")
    if unevaluable_candidates:
        terminal_blockers.append("incomplete-score-coverage")
    if not ok_combos:
        terminal_blockers.append("no-evaluable-combinations")
    if not terminal_blockers:
        terminal_blockers.append("no-protected-structural-improvement")

    payload = {
        "status": "candidate-found"
        if found_candidates
        else (
            "incomplete-score-coverage"
            if unevaluable_candidates and not found_candidates
            else "terminal-component-subset-exhausted"
        ),
        "candidate_found": bool(found_candidates),
        "required_assignments": _protected_assignment_map(required_assignments),
        "max_normalized_diff_lines": max_normalized_diff_lines,
        "source_components": list(source_components),
        "score_coverage": {
            "ok_combinations": len(ok_combos),
            "evaluable_combinations": len(evaluable_candidates),
            "unevaluable_combinations": len(unevaluable_candidates),
            "unevaluable_candidate_ids": [
                candidate["candidate_id"] for candidate in unevaluable_candidates
            ],
        },
        "ranked_candidates": ranked_candidates,
        "preserving_plateau_candidates": preserving_candidates,
        "lower_drift_lost_protected_candidates": lower_drift_lost,
        "skipped_pairs": skipped_pairs,
        "terminal_blockers": terminal_blockers,
        "next_actions": [],
    }
    if found_candidates:
        payload["best_candidate"] = found_candidates[0]
    if preserving_candidates:
        payload["best_preserving_candidate"] = preserving_candidates[0]
    if payload["status"] != "candidate-found":
        payload["terminal_blocker"] = (
            "incomplete-score-coverage"
            if payload["status"] == "incomplete-score-coverage"
            else "protected-structural-synthesis-exhausted"
        )
    if unevaluable_candidates:
        payload["next_actions"].append(
            {
                "kind": "complete-score-coverage",
                "guidance": (
                    "Re-run combine with a score command that emits structural_guard "
                    "and target-score assignment evidence for every ok combination."
                ),
            }
        )
    if skipped_pairs:
        payload["next_actions"].append(
            {
                "kind": "split-overlapping-components",
                "guidance": (
                    "Use --range to split broad overlapping hunks before retrying the protected synthesis lane."
                ),
            }
        )
    if lower_drift_lost:
        payload["next_actions"].append(
            {
                "kind": "repair-lower-drift-protected-loss",
                "guidance": (
                    "Use lower-drift lost-protected candidates as structural seeds "
                    "and steer the missing protected assignments back into place."
                ),
            }
        )
    if preserving_candidates and not found_candidates:
        payload["next_actions"].append(
            {
                "kind": "extend-preserving-plateau",
                "guidance": (
                    "Keep preserving candidates as the protected plateau and add "
                    "one structural component at a time until normalized_diff_lines "
                    "meets the target."
                ),
            }
        )
    return payload


def _score_byte_score(score_result: dict | None) -> int | None:
    parsed = (score_result or {}).get("parsed_json")
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("byte_score")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _score_preserves(
    score_result: dict | None,
    *,
    required_assignments: set[tuple[int, int]],
    max_byte_score: int | None,
) -> bool:
    parsed = (score_result or {}).get("parsed_json")
    if not isinstance(parsed, dict):
        return False
    if max_byte_score is not None:
        byte_score = _score_byte_score(score_result)
        if byte_score is None or byte_score > max_byte_score:
            return False
    return required_assignments <= _assignment_keys_from_score(score_result)


def _byte_score_from_obj(obj) -> int | None:
    score = (
        obj.get("byte_score")
        if isinstance(obj, dict)
        else getattr(obj, "byte_score", None)
    )
    return score if isinstance(score, int) and not isinstance(score, bool) else None


def _best_byte_score(result) -> int | None:
    """Report byte-best independently from directed-best ordering."""
    scores: list[int] = []
    for art in result.best:
        score = _byte_score_from_obj(art)
        if score is not None:
            scores.append(score)
    for meta in getattr(result, "directed_telemetry", []) or []:
        score = _byte_score_from_obj(meta)
        if score is not None:
            scores.append(score)
    return min(scores) if scores else None


@search_app.command("retained-frontiers")
def retained_frontiers_cmd(
    functions: Annotated[
        Optional[list[str]],
        typer.Option(
            "--function",
            "-f",
            help="Function name to include. May be passed multiple times.",
        ),
    ] = None,
    artifacts: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--artifact",
            "-a",
            help="JSON artifact file or directory to scan. Repeatable.",
        ),
    ] = None,
    artifact_globs: Annotated[
        Optional[list[str]],
        typer.Option(
            "--artifact-glob",
            "-g",
            help="Glob of JSON artifacts, relative to repo root unless absolute.",
        ),
    ] = None,
    diagnostics_root: Annotated[
        Path,
        typer.Option(
            "--diagnostics-root",
            help=(
                "Diagnostics root to scan recursively when no artifacts or globs are supplied."
            ),
        ),
    ] = Path("build/diagnostics"),
    max_files: Annotated[
        int,
        typer.Option(
            "--max-files",
            help="Abort if discovery matches more JSON files than this limit.",
        ),
    ] = 2000,
    json_out: Annotated[
        bool,
        typer.Option("--json/--text", help="Emit JSON or compact text."),
    ] = True,
) -> None:
    """Rank retained frontiers and suppress lanes closed by terminal evidence."""
    melee_root = _compute_melee_root()
    try:
        payload = triage_retained_frontiers(
            repo_root=melee_root,
            functions=functions,
            artifacts=artifacts,
            artifact_globs=artifact_globs,
            diagnostics_root=diagnostics_root,
            max_files=max_files,
        )
    except RetainedFrontierTriageError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(render_retained_frontier_text(payload))

    if payload.get("status") != "actionable":
        raise typer.Exit(code=3)


@search_app.command("triage")
def triage_cmd(
    base: Annotated[
        Path,
        typer.Option(
            "--base",
            help="Retained/base source file to compare candidates against.",
        ),
    ],
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate source file, or CANDIDATE_ID=path. May be passed multiple times."
            ),
        ),
    ] = None,
    telemetry: Annotated[
        Optional[Path],
        typer.Option(
            "--telemetry",
            help=("JSON from debug search run/directed containing directed_telemetry."),
        ),
    ] = None,
    score_command: Annotated[
        Optional[str],
        typer.Option(
            "--score-command",
            help=(
                "Optional command template to score each candidate. Use {candidate} as the source path placeholder."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Triage directed-search candidates by source delta and proof movement."""
    if not base.is_file():
        raise typer.BadParameter(f"base source not found: {base}")
    candidate_specs = candidates or []
    if not candidate_specs:
        raise typer.BadParameter("pass at least one --candidate")

    base_text = base.read_text()
    telemetry_entries = _load_triage_telemetry(telemetry)
    results = [
        _triage_candidate(
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            base_text=base_text,
            telemetry=telemetry_entries,
            score_command=score_command,
        )
        for candidate_id, candidate_path in (
            _parse_triage_candidate(spec) for spec in candidate_specs
        )
    ]
    payload = {
        "base": str(base),
        "base_source_hash": _source_hash(base_text),
        "telemetry_count": len(telemetry_entries),
        "candidates": results,
    }
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"Base: {base}")
    typer.echo(f"Telemetry entries: {len(telemetry_entries)}")
    for result in results:
        typer.echo("")
        typer.echo(f"== {result['candidate_id']} ==")
        typer.echo(f"  path: {result['path']}")
        if result.get("byte_score") is not None:
            typer.echo(f"  byte_score: {result['byte_score']}")
        progress = result["assignment_progress"]
        if progress["satisfied"]:
            typer.echo("  satisfied: " + ", ".join(progress["satisfied"]))
        if progress["blocked"]:
            typer.echo("  blocked: " + ", ".join(progress["blocked"]))
        if progress["abstained"]:
            typer.echo("  abstained: " + ", ".join(progress["abstained"]))
        if result["assignment_clusters"]:
            typer.echo("  clusters: " + "; ".join(result["assignment_clusters"]))
        if result["generated_artifacts"]:
            typer.echo(
                "  generated artifacts: " + ", ".join(result["generated_artifacts"])
            )
        typer.echo("  source deltas:")
        for delta in result["source_deltas"]:
            typer.echo(
                f"    - {delta['kind']} (+{delta['added_count']} / -{delta['removed_count']})"
            )
        typer.echo("  naturalization:")
        for suggestion in result["naturalization_suggestions"]:
            typer.echo(f"    - {suggestion}")
        score_result = result.get("score_result")
        if score_result is not None:
            typer.echo(f"  score command: returncode={score_result['returncode']}")


@search_app.command("combine")
def combine_cmd(
    base: Annotated[
        Path,
        typer.Option(
            "--base",
            help="Retained/base source file used as the recombination anchor.",
        ),
    ],
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate source file, or CANDIDATE_ID=path. May be passed multiple times."
            ),
        ),
    ] = None,
    telemetry: Annotated[
        Optional[Path],
        typer.Option(
            "--telemetry",
            help=("JSON from debug search run/directed containing directed_telemetry."),
        ),
    ] = None,
    out_dir: Annotated[
        Path,
        typer.Option(
            "--out-dir",
            help="Directory where combined candidate sources are written.",
        ),
    ] = Path("build/search-combined"),
    score_command: Annotated[
        Optional[str],
        typer.Option(
            "--score-command",
            help=(
                "Optional command template to score each combined candidate. "
                "Use {candidate} as the generated source path placeholder."
            ),
        ),
    ] = None,
    manual_range_specs: Annotated[
        Optional[list[str]],
        typer.Option(
            "--range",
            help=(
                "Manual subhunk range CANDIDATE_ID:BASE_START-BASE_END="
                "CANDIDATE_START-CANDIDATE_END. When present for a candidate, "
                "combine uses those subhunks instead of broad auto hunks."
            ),
        ),
    ] = None,
    protect_assignment_specs: Annotated[
        Optional[list[str]],
        typer.Option(
            "--protect-assignment",
            help=(
                "Required protected assignment IG:PHYS to preserve while evaluating structural recombinations."
            ),
        ),
    ] = None,
    max_normalized_diff_lines: Annotated[
        Optional[int],
        typer.Option(
            "--max-normalized-diff-lines",
            help=(
                "Target structural_guard.normalized_diff_lines threshold for protected synthesis summaries."
            ),
        ),
    ] = None,
    source_components: Annotated[
        Optional[list[str]],
        typer.Option(
            "--source-component",
            help=(
                "Named source component represented by the candidate set. May "
                "be repeated and is reported in synthesis summaries."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Recombine complementary directed-search candidate source hunks."""
    if not base.is_file():
        raise typer.BadParameter(f"base source not found: {base}")
    candidate_specs = candidates or []
    if len(candidate_specs) < 2:
        raise typer.BadParameter("pass at least two --candidate values")

    base_text = base.read_text()
    telemetry_entries = _load_triage_telemetry(telemetry)
    manual_ranges = [_parse_manual_range(spec) for spec in (manual_range_specs or [])]
    required_assignments = {
        _parse_assignment_spec(spec) for spec in (protect_assignment_specs or [])
    }
    loaded = [
        _load_combine_candidate(
            spec=spec,
            base_text=base_text,
            telemetry=telemetry_entries,
            manual_ranges=manual_ranges,
        )
        for spec in candidate_specs
    ]
    combos = [
        _combine_candidate_pair(
            base_text=base_text,
            out_dir=out_dir,
            left=left,
            right=right,
            score_command=score_command,
        )
        for left, right in combinations(loaded, 2)
    ]
    terminal_summary = _combine_terminal_summary(combos, loaded)
    payload = {
        "base": str(base),
        "base_source_hash": _source_hash(base_text),
        "telemetry_count": len(telemetry_entries),
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "path": str(item["path"]),
                "source_hash": item["source_hash"],
                "hunk_count": len(item["hunks"]),
                "clusters": _assignment_clusters(item["meta"]),
                "assignment_progress": _assignment_progress(item["meta"]),
            }
            for item in loaded
        ],
        "combinations": combos,
    }
    if terminal_summary is not None:
        payload["terminal_summary"] = terminal_summary
    if required_assignments:
        payload["protected_structural_synthesis"] = (
            _combine_protected_structural_synthesis_summary(
                combos,
                required_assignments=required_assignments,
                max_normalized_diff_lines=max_normalized_diff_lines,
                source_components=source_components or [],
            )
        )
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"Base: {base}")
    typer.echo(f"Telemetry entries: {len(telemetry_entries)}")
    synthesis = payload.get("protected_structural_synthesis")
    if isinstance(synthesis, dict):
        typer.echo(
            "Protected synthesis: "
            f"{synthesis['status']} "
            f"({synthesis['score_coverage']['evaluable_combinations']}/"
            f"{synthesis['score_coverage']['ok_combinations']} scored)"
        )
    for combo in combos:
        typer.echo("")
        typer.echo(f"== {' + '.join(combo['parents'])} ==")
        typer.echo(f"  status: {combo['status']}")
        typer.echo(f"  attribution: {combo['attribution']}")
        if combo.get("clusters"):
            typer.echo("  clusters: " + "; ".join(combo["clusters"]))
        if combo["status"] != "ok":
            typer.echo(f"  reason: {combo.get('reason')}")
            continue
        typer.echo(f"  merge strategy: {combo['merge_strategy']}")
        typer.echo(f"  output: {combo['path']}")
        progress = combo["assignment_union"]
        if progress["satisfied"]:
            typer.echo("  satisfied union: " + ", ".join(progress["satisfied"]))
        if combo.get("score_result") is not None:
            typer.echo(
                f"  score command: returncode={combo['score_result']['returncode']}"
            )


@search_app.command("minimize")
def minimize_cmd(
    base: Annotated[
        Path,
        typer.Option(
            "--base",
            help="Retained/base source file used as the minimization anchor.",
        ),
    ],
    candidate: Annotated[
        str,
        typer.Option(
            "--candidate",
            help="Candidate source file, or CANDIDATE_ID=path.",
        ),
    ],
    manual_range_specs: Annotated[
        Optional[list[str]],
        typer.Option(
            "--range",
            help=(
                "Manual subhunk range CANDIDATE_ID:BASE_START-BASE_END=CANDIDATE_START-CANDIDATE_END. May be repeated."
            ),
        ),
    ] = None,
    preserve_assignments: Annotated[
        Optional[list[str]],
        typer.Option(
            "--preserve-assignment",
            help="Required satisfied assignment IG:PHYS, e.g. 42:3.",
        ),
    ] = None,
    max_byte_score: Annotated[
        Optional[int],
        typer.Option(
            "--max-byte-score",
            help="Reject minimized candidates with byte_score above this value.",
        ),
    ] = None,
    score_command: Annotated[
        str,
        typer.Option(
            "--score-command",
            help=(
                "Command template used to score each minimized candidate. "
                "Use {candidate} as the generated source path placeholder."
            ),
        ),
    ] = "",
    out: Annotated[
        Path,
        typer.Option("--out", help="Output path for the minimized source."),
    ] = Path("build/search-minimized/minimized.c"),
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Delta-reduce candidate subhunks while preserving proof assignments."""
    if not base.is_file():
        raise typer.BadParameter(f"base source not found: {base}")
    if not score_command:
        raise typer.BadParameter("--score-command is required for minimization")
    base_text = base.read_text()
    manual_ranges = [_parse_manual_range(spec) for spec in (manual_range_specs or [])]
    loaded = _load_combine_candidate(
        spec=candidate,
        base_text=base_text,
        telemetry=[],
        manual_ranges=manual_ranges,
    )
    hunks = list(loaded["hunks"])
    if not hunks:
        raise typer.BadParameter("candidate has no source hunks to minimize")
    required = {_parse_assignment_spec(spec) for spec in (preserve_assignments or [])}

    out.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = out.parent / f".{out.stem}-minimize"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    current = list(hunks)
    initial_text = _merge_source_hunks(base_text, current)
    if initial_text is None:
        raise typer.BadParameter(
            "candidate hunks overlap; pass narrower --range values"
        )
    initial_path = scratch_dir / "initial.c"
    initial_path.write_text(initial_text)
    best_score = _run_triage_score_command(
        score_command,
        candidate_path=initial_path,
    )
    if not _score_preserves(
        best_score,
        required_assignments=required,
        max_byte_score=max_byte_score,
    ):
        payload = {
            "status": "failed",
            "reason": "initial-candidate-does-not-preserve-objective",
            "candidate_id": loaded["candidate_id"],
            "score_result": best_score,
        }
        if json_out:
            typer.echo(json.dumps(payload, indent=2))
            return
        typer.echo(payload["reason"])
        raise typer.Exit(1)

    removed: list[dict] = []
    for index, hunk in enumerate(list(current), 1):
        trial = [item for item in current if item is not hunk]
        trial_text = _merge_source_hunks(base_text, trial)
        if trial_text is None:
            continue
        trial_path = scratch_dir / f"trial-{index}.c"
        trial_path.write_text(trial_text)
        trial_score = _run_triage_score_command(
            score_command,
            candidate_path=trial_path,
        )
        if _score_preserves(
            trial_score,
            required_assignments=required,
            max_byte_score=max_byte_score,
        ):
            current = trial
            removed.append(_hunk_summary(hunk))
            best_score = trial_score

    minimized_text = _merge_source_hunks(base_text, current)
    if minimized_text is None:
        raise typer.BadParameter("minimized hunks unexpectedly overlap")
    out.write_text(minimized_text)
    final_score = _run_triage_score_command(score_command, candidate_path=out)
    payload = {
        "status": "ok",
        "candidate_id": loaded["candidate_id"],
        "path": str(out),
        "source_hash": _source_hash(minimized_text),
        "required_assignments": [f"ig{ig}->r{phys}" for ig, phys in sorted(required)],
        "kept_hunks": [_hunk_summary(hunk) for hunk in current],
        "removed_hunks": removed,
        "score_result": final_score,
    }
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"status: {payload['status']}")
    typer.echo(f"output: {payload['path']}")
    if removed:
        typer.echo(f"removed hunks: {len(removed)}")
    typer.echo("preserved: " + ", ".join(payload["required_assignments"]))


def _read_directed_force_phys_from_diff_payload(
    *,
    function: str,
    melee_root: Path,
    verify: bool,
    checkdiff_timeout: float,
    force_vector_probes: bool,
) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "target",
        "force-phys-from-diff",
        "--function",
        function,
        "--json",
        "--checkdiff-timeout",
        f"{checkdiff_timeout:g}",
        "--force-vector-checkdiff-timeout",
        f"{checkdiff_timeout:g}",
    ]
    if verify:
        cmd.append("--verify")
        if not force_vector_probes:
            cmd.append("--no-force-vector-probes")
    proc = subprocess.run(
        cmd,
        cwd=melee_root / "tools" / "melee-agent",
        capture_output=True,
        text=True,
        timeout=max(checkdiff_timeout * 8, 120.0),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            "debug target force-phys-from-diff failed"
            + (f": {detail}" if detail else "")
        )
    payload = json.loads(proc.stdout)
    if verify:
        verify_payload = payload.get("force_vector_verify") or {}
        union = (
            verify_payload.get("union") if isinstance(verify_payload, dict) else None
        )
        if not verify_payload.get("ran") or not isinstance(union, dict):
            raise RuntimeError(
                f"directed force-vector verification did not run: {verify_payload.get('reason', 'no union probe')}"
            )
        if not union.get("match"):
            raise RuntimeError(
                "directed force-vector union did not match "
                f"(status={union.get('status')}, returncode={union.get('returncode')})"
            )
    return payload


def _derive_directed_force_phys_from_diff(
    *,
    function: str,
    melee_root: Path,
    verify: bool,
    checkdiff_timeout: float,
    force_vector_probes: bool,
    default_class_id: int,
) -> tuple[dict[int, int], int, dict]:
    payload = _read_directed_force_phys_from_diff_payload(
        function=function,
        melee_root=melee_root,
        verify=verify,
        checkdiff_timeout=checkdiff_timeout,
        force_vector_probes=force_vector_probes,
    )
    force_phys_csv = payload.get("force_phys_csv") or ""
    force_phys, class_id = _parse_directed_force_phys(
        force_phys_csv,
        default_class_id=default_class_id,
    )
    return force_phys, class_id, payload


def _derive_directed_force_phys_groups_from_diff(
    *,
    function: str,
    melee_root: Path,
    verify: bool,
    checkdiff_timeout: float,
    force_vector_probes: bool,
    default_class_id: int,
) -> tuple[dict[int, dict[int, int]], dict]:
    payload = _read_directed_force_phys_from_diff_payload(
        function=function,
        melee_root=melee_root,
        verify=verify,
        checkdiff_timeout=checkdiff_timeout,
        force_vector_probes=force_vector_probes,
    )
    force_phys_csv = payload.get("force_phys_csv") or ""
    groups = _parse_directed_force_phys_groups(
        force_phys_csv,
        default_class_id=default_class_id,
    )
    return groups, payload


@search_app.command("run")
def run_cmd(
    function: Annotated[
        str, typer.Option("--function", "-f", help="Function name to search for.")
    ],
    unit: Annotated[
        str,
        typer.Option(
            "--unit", "-u", help="Translation unit path (e.g. melee/gr/quatlib)."
        ),
    ],
    store: Annotated[
        Optional[Path],
        typer.Option(
            "--store", help="Artifact store directory. Defaults to build/search-store."
        ),
    ] = None,
    seeds: Annotated[
        Optional[list[str]],
        typer.Option(
            "--seed",
            help=(
                "Seed source files (.c), optionally ID=path. May be passed multiple times."
            ),
        ),
    ] = None,
    no_remote: Annotated[
        bool,
        typer.Option("--no-remote/--remote", help="Skip remote permuter producers."),
    ] = False,
    remotes: Annotated[
        str,
        typer.Option(
            "--remotes",
            help="Comma-separated remote names (default: coder1,coder2,coder3).",
        ),
    ] = "coder1,coder2,coder3",
    max_iters: Annotated[
        int,
        typer.Option("--max-iters", help="Maximum scheduler iterations."),
    ] = 10,
    dry_compiler: Annotated[
        bool,
        typer.Option(
            "--dry-compiler", help="Use stub compiler (no real mwcc/wibo). For testing."
        ),
    ] = False,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone used for remote producer jobs.",
        ),
    ] = Path("~/code/decomp-permuter"),
    directed_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--directed-force-phys",
            help=(
                "Enable directed allocator scoring with a force-phys proof "
                "vector, e.g. 0:58:4,0:44:4 or class0:ig58:phys=r4."
            ),
        ),
    ] = None,
    directed_from_diff: Annotated[
        bool,
        typer.Option(
            "--directed-from-diff/--no-directed-from-diff",
            help=(
                "Derive the directed force-phys proof from `debug target force-phys-from-diff` before running."
            ),
        ),
    ] = False,
    directed_class: Annotated[
        int,
        typer.Option(
            "--directed-class",
            help="Default register class for unscoped directed proof entries.",
        ),
    ] = 0,
    directed_verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help=(
                "With --directed-from-diff, require force-vector verification "
                "to run and byte-match before the search starts."
            ),
        ),
    ] = False,
    directed_force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--directed-force-vector-probes/--no-directed-force-vector-probes",
            help=(
                "With --directed-from-diff --verify, include singleton and prefix force-vector diagnostic probes."
            ),
        ),
    ] = True,
    directed_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--directed-checkdiff-timeout",
            help=(
                "Timeout in seconds for directed proof derivation and force-vector verification checkdiff runs."
            ),
        ),
    ] = 60.0,
    directed_pcdump_timeout: Annotated[
        int,
        typer.Option(
            "--directed-pcdump-timeout",
            help="Timeout in seconds for directed local pcdump compilation.",
        ),
    ] = 120,
) -> None:
    """Run a search over source variants for FUNCTION in UNIT.

    Uses seed source files as the starting candidate pool, optionally
    combined with remote permuter producers.  Prints a JSON summary
    including accounting when done.
    """
    from src.search.adapters import (
        _DryByteScorer,
        _DryCheckdiffVerifier,
        _DryLocalCompiler,
        RealByteScorer,
        RealCheckdiffVerifier,
        RealLocalCompiler,
        RealRemotePermuterClient,
    )
    from src.search.artifact import CompileManifest, CompileSpec
    from src.search.backends import PlainLocalBackend
    from src.search.producers import PermuterJobProducer
    from src.search.scheduler import DefaultScheduler
    from src.search.scoring import ByteScorePipeline, DefaultSchedulePolicy
    from src.search.sources import SeedListSource
    from src.search.store import ArtifactStore
    from src.search.types import Budget, TargetSpec

    melee_root = _compute_melee_root()
    perm_root = perm_root.expanduser()

    # Resolve expected .o path from report.json
    expected_obj = _resolve_expected_obj(melee_root, function, unit)

    target = TargetSpec(function=function, unit=unit, expected_obj=expected_obj)

    directed_force_phys_map: dict[int, int] | None = None
    directed_class_id = directed_class
    directed_source = None
    directed_derivation_payload: dict | None = None
    if directed_force_phys and directed_from_diff:
        typer.echo(
            "error: pass either --directed-force-phys or --directed-from-diff, not both",
            err=True,
        )
        raise typer.Exit(2)
    try:
        if directed_force_phys:
            directed_force_phys_map, directed_class_id = _parse_directed_force_phys(
                directed_force_phys,
                default_class_id=directed_class,
            )
            directed_source = "explicit"
        elif directed_from_diff:
            (
                directed_force_phys_map,
                directed_class_id,
                directed_derivation_payload,
            ) = _derive_directed_force_phys_from_diff(
                function=function,
                melee_root=melee_root,
                verify=directed_verify,
                checkdiff_timeout=directed_checkdiff_timeout,
                force_vector_probes=directed_force_vector_probes,
                default_class_id=directed_class,
            )
            directed_source = "force-phys-from-diff"
    except (
        ValueError,
        RuntimeError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        typer.echo(f"error: directed objective setup failed: {exc}", err=True)
        raise typer.Exit(2) from exc

    directed_manifest = None
    if directed_force_phys_map is not None:
        directed_manifest = {
            "enabled": True,
            "source": directed_source,
            "class_id": directed_class_id,
            "proof_force_phys": {
                str(ig_idx): phys
                for ig_idx, phys in sorted(directed_force_phys_map.items())
            },
            "proof_force_phys_csv": _format_directed_force_phys(
                directed_force_phys_map,
                directed_class_id,
            ),
            "from_diff_verified": (
                bool(directed_derivation_payload.get("force_vector_verify"))
                if directed_derivation_payload is not None
                else None
            ),
        }

    # Store
    if store is None:
        store = melee_root / "build" / "search-store"
    artifact_store = ArtifactStore(root=store)

    # Adapters
    if dry_compiler:
        compiler = _DryLocalCompiler()
        scorer = _DryByteScorer()
        verifier = _DryCheckdiffVerifier()
    else:
        compiler = RealLocalCompiler(melee_root)
        scorer = RealByteScorer()
        verifier = RealCheckdiffVerifier(melee_root)

    # Sources — load seed texts first; they are candidate inputs. Directed
    # proof/control baselines stay anchored to the current TU source even
    # when a non-baseline seed is provided.
    seed_texts: list[str] = []
    seed_entries: list[dict[str, str]] = []
    seed_variants: list[tuple[str, str]] = []
    for raw_seed in seeds or []:
        candidate_id, seed_path = _parse_run_seed(raw_seed, melee_root=melee_root)
        seed_text = seed_path.read_text(encoding="utf-8")
        seed_texts.append(seed_text)
        seed_variants.append((candidate_id, seed_text))
        seed_entries.append(
            {
                "candidate_id": candidate_id,
                "path": str(seed_path),
                "source_hash": _source_hash(seed_text),
            }
        )
    source = SeedListSource(seed_variants)
    sources = [source]
    base_seed_text = seed_texts[0] if seed_texts else None
    tu_source_path = melee_root / "src" / f"{unit}.c"
    baseline_source_text = (
        tu_source_path.read_text(encoding="utf-8") if tu_source_path.exists() else None
    )
    permuter_dir = _resolve_permuter_function_dir(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    )
    remote_ready_permuter_dir = (
        permuter_dir if _is_remote_ready_permuter_dir(permuter_dir) else None
    )

    # Persist the compile manifest ONCE (content-addressed: same inputs ->
    # same path). The artifact's manifest_path will point here, and
    # base_context_hash is the hash of the SAME blob stored in the manifest
    # so compute_candidate_id and the manifest stay consistent (spec §3.1).
    cflags_list = _CFLAGS.split()
    include_paths = _resolve_include_paths(melee_root, unit)
    base_context_blob_text = "\n".join(seed_texts)
    base_context_blob = artifact_store.put_source(base_context_blob_text)
    base_context_hash = hashlib.sha256(base_context_blob_text.encode()).hexdigest()[:32]
    obj_rel = f"build/GALE01/src/{unit}.o"
    compile_command = [
        "ninja",
        obj_rel,
    ]
    manifest = CompileManifest(
        compile_command=compile_command,
        cflags=cflags_list,
        include_paths=include_paths,
        base_context_blob=base_context_blob,
        permuter_compile_sh=(
            remote_ready_permuter_dir / "compile.sh"
            if remote_ready_permuter_dir is not None
            else None
        ),
        permuter_settings_toml=(
            remote_ready_permuter_dir / "settings.toml"
            if remote_ready_permuter_dir is not None
            else None
        ),
        directed_objective=directed_manifest,
    )
    manifest_path = artifact_store.put_manifest(manifest)

    # Backend — one spec factory parameterised by backend_mode.
    cflags_hash = hashlib.sha256(_CFLAGS.encode()).hexdigest()[:16]

    def _make_spec(backend_mode: str) -> CompileSpec:
        return CompileSpec(
            target_id=f"{function}@{unit}",
            cflags_hash=cflags_hash,
            base_context_hash=base_context_hash,
            toolchain_fingerprint="mwcc_233_163n",
            backend_mode=backend_mode,
            manifest_path=manifest_path,
        )

    backend = PlainLocalBackend(
        compiler=compiler,
        store=artifact_store,
        compile_spec_factory=lambda variant: _make_spec("plain-local"),
        target=target,
    )

    directed_config = None
    directed_summary = None
    directed_pipeline = None
    if directed_force_phys_map is not None:
        from src.search.directed.contracts import DirectedSchedulerConfig
        from src.search.directed.objective import (
            PreflightError,
            allows_force_phys_assignment_fallback,
            build_directed_objective,
            preflight_objective,
        )
        from src.search.directed.pcdump_backend import PcdumpLocalBackend
        from src.search.directed.scorer import DirectedScorePipeline

        preflight_status = "ok"
        preflight_ok = True
        pcdump_backend = PcdumpLocalBackend(
            melee_root=melee_root,
            unit=unit,
            target=target,
            store=artifact_store,
            compile_spec_factory=lambda variant: _make_spec("pcdump-local"),
            timeout=directed_pcdump_timeout,
        )
        try:
            objective = build_directed_objective(
                melee_root=melee_root,
                search_target=target,
                function=function,
                unit=unit,
                proof_force_phys=directed_force_phys_map,
                class_id=directed_class_id,
                backend=pcdump_backend,
                baseline_source_text=baseline_source_text,
            )
            preflight_objective(objective)
        except PreflightError as exc:
            reason = str(exc)
            if not allows_force_phys_assignment_fallback(
                reason,
                proof_force_phys=directed_force_phys_map,
                objective=objective,
            ):
                typer.echo(
                    f"error: directed objective preflight failed: {exc}",
                    err=True,
                )
                raise typer.Exit(4) from exc
            preflight_status = f"fallback:{reason}"
            preflight_ok = False
        except Exception as exc:
            typer.echo(
                f"error: directed objective build failed: {exc}",
                err=True,
            )
            raise typer.Exit(4) from exc

        directed_pipeline = _SearchRunDirectedPipeline(
            byte_pipeline=ByteScorePipeline(scorer),
            directed_pipeline=DirectedScorePipeline(plateau_n=3),
        )
        directed_config = DirectedSchedulerConfig(
            objective=objective,
            score_pipeline=directed_pipeline,
            backend=pcdump_backend,
            plateau_n=3,
        )
        directed_source_text = (
            base_seed_text if base_seed_text is not None else baseline_source_text
        )
        if directed_source_text is not None:
            from src.search.directed.run import _build_directed_source

            sources.append(
                _build_directed_source(
                    source_text=directed_source_text,
                    target=target,
                    pcdump_backend=pcdump_backend,
                    objective=objective,
                    function=function,
                    unit=unit,
                    proof_force_phys=directed_force_phys_map,
                )
            )
        directed_summary = {
            **(directed_manifest or {}),
            "baseline_source_hash": objective.baseline_source_hash,
            "baseline_pcdump_path": (
                str(objective.baseline_pcdump_path)
                if objective.baseline_pcdump_path is not None
                else None
            ),
            "objective_iter_by_original_ig": {
                str(ig_idx): iter_idx
                for ig_idx, iter_idx in sorted(
                    objective.objective_iter_by_original_ig.items()
                )
            },
            "preflight": preflight_status,
            "preflight_ok": preflight_ok,
        }

    # Producers
    producers = []
    if not no_remote and not dry_compiler:
        remote_list = [r.strip() for r in remotes.split(",") if r.strip()]
        if remote_list:
            if remote_ready_permuter_dir is None:
                missing = _missing_remote_ready_permuter_files(permuter_dir)
                typer.echo(
                    "[warn] remote producers disabled: "
                    f"{permuter_dir} is missing {', '.join(missing)}. "
                    "Run `melee-agent debug permute bootstrap` first.",
                    err=True,
                )
            else:
                client = RealRemotePermuterClient(melee_root)
                producers.append(
                    PermuterJobProducer(
                        client=client,
                        store=artifact_store,
                        remotes=remote_list,
                        compile_spec_factory=lambda text: _make_spec("permuter-job"),
                        permuter_base_dir=remote_ready_permuter_dir,
                        base_source_text=base_seed_text,
                    )
                )

    # Pipeline + scheduler
    pipeline = directed_pipeline or ByteScorePipeline(scorer)
    policy = DefaultSchedulePolicy()
    budget = Budget(max_iters=max_iters)
    scheduler = DefaultScheduler(store=artifact_store, verifier=verifier)

    def _emit_progress(event: dict) -> None:
        name = event.get("event", "progress")
        producer = event.get("producer")
        prefix = f"[search] {name}"
        fields: list[str] = []
        if producer:
            fields.append(f"producer={producer}")
        jobs = event.get("jobs") or []
        if jobs:
            fields.append("jobs=" + ",".join(str(job) for job in jobs))
            if len(jobs) == 1:
                fields.append(f"job={jobs[0]}")
        for key in (
            "remote",
            "iteration",
            "poll",
            "state",
            "harvested",
            "detail",
            "reason",
            "elapsed_seconds",
        ):
            value = event.get(key)
            if value not in (None, ""):
                fields.append(f"{key}={value}")
        if fields:
            typer.echo(f"{prefix} " + " ".join(fields), err=True)
        else:
            typer.echo(prefix, err=True)

    result = scheduler.run(
        sources=sources,
        backends=[backend],
        producers=producers,
        pipeline=pipeline,
        target=target,
        budget=budget,
        policy=policy,
        progress=_emit_progress if producers else None,
        directed=directed_config,
    )

    best_art = result.best[0] if result.best else None
    # Derive best_directed_score: prefer directed_telemetry (post-directed
    # scoring), fall back to best_art.directed_score if set.
    best_directed_score = None
    if result.directed_telemetry:
        valid_disps = [
            m.displacement
            for m in result.directed_telemetry
            if getattr(m, "valid", False)
            and getattr(m, "displacement", None) is not None
        ]
        if valid_disps:
            best_directed_score = max(valid_disps)
    if best_directed_score is None and best_art is not None:
        best_directed_score = best_art.directed_score

    summary = {
        "function": function,
        "unit": unit,
        "matched": result.matched is not None,
        "best_byte_score": _best_byte_score(result),
        "best_directed_score": best_directed_score,
        "candidates": len(result.best),
        "accounting": result.accounting,
    }
    if seed_entries:
        summary["seed_candidates"] = seed_entries
    if directed_summary is not None:
        summary["directed"] = directed_summary
        summary["directed_telemetry"] = [
            _meta_to_dict(meta) for meta in result.directed_telemetry
        ]
        if best_art is not None and best_art.directed_meta is not None:
            summary["best_directed_meta"] = _meta_to_dict(best_art.directed_meta)
    typer.echo(json.dumps(summary, indent=2))


def _jsonable_directed_force_phys_groups(
    groups: dict[int, dict[int, int]],
) -> dict[str, dict[str, int]]:
    return {
        str(class_id): {
            str(ig_idx): phys for ig_idx, phys in sorted(force_phys.items())
        }
        for class_id, force_phys in sorted(groups.items())
    }


def _aggregate_directed_class_results(
    *,
    function: str,
    unit: str,
    groups: dict[int, dict[int, int]],
    results: list[tuple[int, dict]],
    derivation_payload: dict | None = None,
) -> dict:
    class_ids = [class_id for class_id, _result in results]
    telemetry: list[dict] = []
    class_entries: list[dict] = []
    gates: list[dict] = []
    accounting_by_class: dict[str, dict] = {}
    stop_reason = None
    stop_condition = None
    producer_failures: list = []
    numeric_accounting_keys = (
        "compiled",
        "compile_failed",
        "score_failed",
        "directed_invalid",
        "iterations",
        "producer_failed",
        "producer_drained",
    )
    accounting_totals = {key: 0 for key in numeric_accounting_keys}
    budget_exhausted = False
    source_shape_values: list[bool] = []
    source_drained_values: list[bool] = []

    for class_id, result in results:
        gate = result.get("gate")
        if isinstance(gate, dict):
            gates.append({"class_id": class_id, **gate})
        accounting = result.get("accounting")
        if isinstance(accounting, dict):
            accounting_by_class[str(class_id)] = accounting
            for key in numeric_accounting_keys:
                value = accounting.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    accounting_totals[key] += value
            if stop_reason is None and isinstance(accounting.get("stop_reason"), str):
                stop_reason = accounting["stop_reason"]
            if stop_condition is None and isinstance(
                accounting.get("stop_condition"),
                dict,
            ):
                stop_condition = dict(accounting["stop_condition"])
            failures = accounting.get("producer_failures")
            if isinstance(failures, list):
                producer_failures.extend(failures)
            budget_exhausted = budget_exhausted or (
                accounting.get("budget_exhausted") is True
            )
            source_shape_values.append(accounting.get("source_shape_drained") is True)
            source_drained_values.append(accounting.get("source_drained") is True)
        for row in result.get("directed_telemetry") or []:
            if isinstance(row, dict):
                telemetry.append({**row, "class_id": class_id})
        class_entries.append(
            {
                "class_id": class_id,
                "proof_force_phys": {
                    str(ig_idx): phys
                    for ig_idx, phys in sorted(groups[class_id].items())
                },
                "result": result,
            }
        )

    if any(gate.get("passed") is True for gate in gates):
        passed_gate = next(gate for gate in gates if gate.get("passed") is True)
        aggregate_gate = {
            "passed": True,
            "reason": passed_gate.get("reason", "attributable_progress"),
            "evidence": {"classes": gates},
        }
    elif gates and all(gate.get("reason") == "no_smooth_gradient" for gate in gates):
        aggregate_gate = {
            "passed": False,
            "reason": "no_smooth_gradient",
            "evidence": {"classes": gates},
        }
    else:
        aggregate_gate = {
            "passed": False,
            "reason": "mixed_class_results",
            "evidence": {"classes": gates},
        }

    accounting = {
        **accounting_totals,
        "budget_exhausted": budget_exhausted,
        "source_shape_drained": bool(source_shape_values) and all(source_shape_values),
        "source_drained": bool(source_drained_values) and all(source_drained_values),
        "class_count": len(class_ids),
        "class_ids": class_ids,
        "per_class": accounting_by_class,
    }
    if stop_reason is not None:
        accounting["stop_reason"] = stop_reason
    if stop_condition is not None:
        accounting["stop_condition"] = stop_condition
    if producer_failures:
        accounting["producer_failures"] = producer_failures
    payload = {
        "function": function,
        "unit": unit,
        "multi_class": True,
        "class_ids": class_ids,
        "proof_force_phys": _jsonable_directed_force_phys_groups(groups),
        "proof_force_phys_csv": _format_directed_force_phys_groups(groups),
        "gate": aggregate_gate,
        "directed_telemetry": telemetry,
        "accounting": accounting,
        "classes": class_entries,
    }
    if derivation_payload is not None:
        payload["from_diff"] = {
            "force_phys_csv": derivation_payload.get("force_phys_csv"),
            "force_vector_verify": derivation_payload.get("force_vector_verify"),
        }
    return payload


@search_app.command("directed")
def directed_cmd(
    function: Annotated[
        str, typer.Option("--function", "-f", help="Function name to match.")
    ],
    unit: Annotated[
        str,
        typer.Option(
            "--unit", "-u", help="Translation unit path (e.g. melee/gr/gricemt)."
        ),
    ],
    store: Annotated[
        Optional[Path],
        typer.Option(
            "--store",
            help="Artifact store directory. Defaults to build/directed-store.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--seed",
            "--source-file",
            help="Use this source file as the initial directed-search seed.",
        ),
    ] = None,
    dry: Annotated[
        bool,
        typer.Option(
            "--dry/--no-dry", help="Use in-memory fakes; no mwcc runs. For testing."
        ),
    ] = False,
    max_iters: Annotated[
        int,
        typer.Option("--max-iters", help="Maximum scheduler iterations."),
    ] = 8,
    directed_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--directed-force-phys",
            "--force-phys",
            help=(
                "Directed force-phys proof vector, e.g. 0:58:4,0:44:4 or class0:ig58:phys=r4."
            ),
        ),
    ] = None,
    directed_from_diff: Annotated[
        bool,
        typer.Option(
            "--directed-from-diff/--no-directed-from-diff",
            help="Derive the directed proof with debug target force-phys-from-diff.",
        ),
    ] = False,
    directed_class: Annotated[
        int,
        typer.Option(
            "--directed-class",
            help="Default register class for unscoped directed proof entries.",
        ),
    ] = 0,
    directed_verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="With --directed-from-diff, require force-vector verification.",
        ),
    ] = False,
    directed_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--directed-checkdiff-timeout",
            help="Timeout in seconds for directed proof derivation.",
        ),
    ] = 60.0,
    directed_pcdump_timeout: Annotated[
        int,
        typer.Option(
            "--directed-pcdump-timeout",
            help="Timeout in seconds for directed local pcdump compilation.",
        ),
    ] = 120,
) -> None:
    """Run the directed (pcdump-guided) search layer for FUNCTION in UNIT.

    In dry mode (--dry), uses in-memory fakes and no real mwcc compilation.
    Prints a JSON result with 'gate', 'directed_telemetry', and 'accounting'.
    """
    import json as _json

    from src.search.directed.run import run_directed

    melee_root = _compute_melee_root()
    source_file = _resolve_source_file(source_file, melee_root=melee_root)
    if store is None:
        store = melee_root / "build" / "directed-store"
    proof_force_phys = None
    proof_force_phys_groups: dict[int, dict[int, int]] | None = None
    class_id = directed_class
    derivation_payload = None
    if directed_force_phys and directed_from_diff:
        typer.echo(
            "error: pass either --directed-force-phys or --directed-from-diff, not both",
            err=True,
        )
        raise typer.Exit(2)
    try:
        if directed_force_phys:
            proof_force_phys_groups = _parse_directed_force_phys_groups(
                directed_force_phys,
                default_class_id=directed_class,
            )
            if len(proof_force_phys_groups) == 1:
                class_id, proof_force_phys = next(iter(proof_force_phys_groups.items()))
        elif directed_from_diff:
            (
                proof_force_phys_groups,
                derivation_payload,
            ) = _derive_directed_force_phys_groups_from_diff(
                function=function,
                melee_root=melee_root,
                verify=directed_verify,
                checkdiff_timeout=directed_checkdiff_timeout,
                force_vector_probes=False,
                default_class_id=directed_class,
            )
            if len(proof_force_phys_groups) == 1:
                class_id, proof_force_phys = next(iter(proof_force_phys_groups.items()))
    except (
        ValueError,
        RuntimeError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        typer.echo(f"error: directed objective setup failed: {exc}", err=True)
        raise typer.Exit(2) from exc

    if proof_force_phys_groups is not None and len(proof_force_phys_groups) > 1:
        class_results: list[tuple[int, dict]] = []
        for sub_class_id, sub_force_phys in sorted(proof_force_phys_groups.items()):
            class_results.append(
                (
                    sub_class_id,
                    run_directed(
                        function=function,
                        unit=unit,
                        melee_root=melee_root,
                        store_dir=store,
                        dry=dry,
                        max_iters=max_iters,
                        proof_force_phys=sub_force_phys,
                        class_id=sub_class_id,
                        source_file=source_file,
                        pcdump_timeout=directed_pcdump_timeout,
                    ),
                )
            )
        typer.echo(
            _json.dumps(
                _aggregate_directed_class_results(
                    function=function,
                    unit=unit,
                    groups=proof_force_phys_groups,
                    results=class_results,
                    derivation_payload=derivation_payload,
                ),
                indent=2,
            )
        )
        return

    res = run_directed(
        function=function,
        unit=unit,
        melee_root=melee_root,
        store_dir=store,
        dry=dry,
        max_iters=max_iters,
        proof_force_phys=proof_force_phys,
        class_id=class_id,
        source_file=source_file,
        pcdump_timeout=directed_pcdump_timeout,
    )
    typer.echo(_json.dumps(res, indent=2))


@search_app.command("status")
def status_cmd() -> None:
    """Show status of the search substrate (store, config)."""
    typer.echo("search substrate: ready")


# Canonical melee include search dirs (mirrors configure.py:includes_base).
_INCLUDES_BASE = ["src", "src/MSL", "src/Runtime", "extern/dolphin/include"]


def _resolve_include_paths(melee_root: Path, unit: str) -> list[str]:
    """Resolve the compiler `-i` include search paths for UNIT.

    Returns absolute paths for the project's canonical include base. Kept as a
    helper so the manifest records the same include set the real compile uses.
    """
    return [str((melee_root / inc).resolve()) for inc in _INCLUDES_BASE]


def _resolve_expected_obj(melee_root: Path, function: str, unit: str) -> Path:
    """Resolve the expected .o path for FUNCTION.

    Tries report.json first; falls back to the conventional build path for UNIT.
    """
    import json as _json

    report = melee_root / "build" / "GALE01" / "report.json"
    if report.exists():
        try:
            data = _json.loads(report.read_text())
            for u in data.get("units", []):
                for fn in u.get("functions", []):
                    if fn.get("name") == function:
                        unit_name = u.get("name", "").removeprefix("main/")
                        return (
                            melee_root / "build" / "GALE01" / "obj" / f"{unit_name}.o"
                        )
        except Exception:
            pass

    # Fallback: derive from unit arg
    return melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"


def _resolve_permuter_function_dir(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> Path:
    """Find a decomp-permuter function dir in either supported location."""
    perm_dir = perm_root / "nonmatchings" / function
    if perm_dir.exists():
        return perm_dir

    worktree_dir = melee_root / "nonmatchings" / function
    if worktree_dir.exists():
        return worktree_dir

    return perm_dir


def _missing_remote_ready_permuter_files(perm_dir: Path) -> list[str]:
    required = ["compile.sh", "settings.toml", "target.o"]
    if not perm_dir.is_dir():
        return ["function dir", *required]
    return [name for name in required if not (perm_dir / name).exists()]


def _is_remote_ready_permuter_dir(perm_dir: Path) -> bool:
    return not _missing_remote_ready_permuter_files(perm_dir)
