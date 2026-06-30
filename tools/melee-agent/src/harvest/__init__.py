from __future__ import annotations

from ._helpers import *  # noqa: F403

@dataclass
class HarvestRequest:
    function: str
    work_bucket: str
    match_percent: float
    file_path: str
    headline_tool: str
    source_file: Path | None
    primary: str = ""
    subcategory: str = ""
    source_actionability: str = ""
    frame_closability_tier: str = ""
    next_command: str = ""
    frame_next_command: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    rebucket_fingerprint: dict[str, str] = field(default_factory=dict)
    terminal_attempt_status: str = ""
    apply: bool = False
    timeout: int = 120
    max_probes: int = 8


@dataclass(frozen=True)
class HarvestFilters:
    where: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    exclude_source_actionability: tuple[str, ...] = ()

    def is_active(self) -> bool:
        return bool(self.where or self.exclude_source_actionability)

    def to_dict(self) -> dict[str, Any] | None:
        if not self.is_active():
            return None
        data: dict[str, Any] = {}
        if self.where:
            data["where"] = {
                key: list(values) for key, values in sorted(self.where.items())
            }
        if self.exclude_source_actionability:
            data["exclude_source_actionability"] = sorted(
                self.exclude_source_actionability
            )
        return data


@dataclass
class HarnessProcessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class HarvestResult:
    function: str
    work_bucket: str
    headline_tool: str
    status: str
    blocker: str | None
    reason: str
    command: list[str]
    candidate_path: str | None
    source_file: str | None
    final_match_percent: float | None
    applied: bool
    details: dict[str, Any] = field(default_factory=dict)
    harness: str | None = None
    primary: str = ""
    subcategory: str = ""
    source_actionability: str = ""
    frame_closability_tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PcdumpPreflightReport:
    enabled: bool
    required_units: list[str] = field(default_factory=list)
    fresh_units: list[str] = field(default_factory=list)
    stale_units: list[str] = field(default_factory=list)
    missing_units: list[str] = field(default_factory=list)
    generated_units: list[str] = field(default_factory=list)
    failed_units: list[str] = field(default_factory=list)
    unsafe_units: list[str] = field(default_factory=list)
    unsafe_sources: list[str] = field(default_factory=list)
    unsafe_processes: list[dict[str, Any]] = field(default_factory=list)
    setup_command: dict[str, Any] | None = None
    dump_commands: list[dict[str, Any]] = field(default_factory=list)
    dump_failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HarnessRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...


class ValidatorRunner(Protocol):
    def __call__(
        self,
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...


class MatchCheckerRunner(Protocol):
    def __call__(
        self,
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...



def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hash_json(value: Any, *, length: int = 16) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:length]


def _source_file_sha256(source_file: Path | None, *, length: int = 16) -> str | None:
    if source_file is None:
        return None
    try:
        return hashlib.sha256(source_file.read_bytes()).hexdigest()[:length]
    except OSError:
        return None


def resolve_source_file(repo_root: Path, file_path: str) -> Path | None:
    """Resolve a taxonomy row source path against repo src first, then root."""
    if not file_path:
        return None
    repo_root = repo_root.resolve()
    raw_path = Path(file_path)
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [repo_root / "src" / raw_path, repo_root / raw_path]

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_relative_to(repo_root):
            return resolved
    return None


def _fingerprint_match_percent(value: Any) -> str:
    score = _float_or_none(value)
    if score is None:
        return ""
    return f"{score:.6f}"


def _queue_row_taxonomy_fingerprint(
    raw: Mapping[str, str],
    *,
    work_bucket: str,
) -> str:
    fields: dict[str, str] = {"work_bucket": work_bucket}
    for field_name in SOURCE_ACTIONABILITY_REBUCKET_FINGERPRINT_FIELDS:
        if field_name == "match_percent":
            fields[field_name] = _fingerprint_match_percent(raw.get(field_name))
        else:
            fields[field_name] = str(raw.get(field_name) or "").strip()
    return _hash_json(fields)


def _queue_row_tool_fingerprint(
    raw: Mapping[str, str],
    *,
    work_bucket: str,
) -> str:
    fields: dict[str, str] = {"work_bucket": work_bucket}
    for field_name in SOURCE_ACTIONABILITY_REBUCKET_ROW_TOOL_FIELDS:
        fields[field_name] = str(raw.get(field_name) or "").strip()
    return _hash_json(fields)


@lru_cache(maxsize=None)
def _harvest_tool_fingerprint(work_bucket: str) -> str | None:
    if work_bucket not in {"register-allocator", "stack-local-layout"}:
        return None
    src_root = Path(__file__).resolve().parent
    tool_paths = [src_root / "cli" / "debug.py"]
    if work_bucket == "stack-local-layout":
        tool_paths.extend(
            [
                src_root / "mwcc_debug" / "pressure_explorer.py",
                src_root / "mwcc_debug" / "frame_reservations.py",
            ]
        )
    hasher = hashlib.sha256()
    for path in tool_paths:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        hasher.update(str(path.relative_to(src_root)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _rebucket_fingerprint_from_raw(
    raw: Mapping[str, str],
    *,
    repo_root: Path,
    work_bucket: str,
) -> dict[str, str]:
    fingerprint = {
        "taxonomy_sha256": _queue_row_taxonomy_fingerprint(
            raw,
            work_bucket=work_bucket,
        ),
        "row_tool_sha256": _queue_row_tool_fingerprint(
            raw,
            work_bucket=work_bucket,
        ),
    }
    tool_sha256 = _harvest_tool_fingerprint(work_bucket)
    if tool_sha256 is not None:
        fingerprint["tool_sha256"] = tool_sha256
    source_sha256 = _source_file_sha256(
        resolve_source_file(repo_root, (raw.get("file_path") or "").strip())
    )
    if source_sha256 is not None:
        fingerprint["source_sha256"] = source_sha256
    return fingerprint


def _rebucket_fingerprint_from_request(request: HarvestRequest) -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for key in ("taxonomy_sha256", "row_tool_sha256", "tool_sha256"):
        value = request.rebucket_fingerprint.get(key)
        if value:
            fingerprint[key] = value
    source_sha256 = _source_file_sha256(request.source_file)
    if source_sha256 is not None:
        fingerprint["source_sha256"] = source_sha256
    return fingerprint


def load_target_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("target map must be a JSON object keyed by function")
    target_map: dict[str, dict[str, Any]] = {}
    for function, facts in raw.items():
        if isinstance(facts, dict):
            target_map[str(function)] = dict(facts)
        else:
            target_map[str(function)] = {"target": facts}
    return target_map


def _validate_filter_fields(
    filters: HarvestFilters | None,
    fieldnames: list[str] | None,
) -> None:
    if filters is None or not filters.is_active():
        return
    available = set(fieldnames or [])
    for field_name in filters.where:
        if field_name not in available:
            raise ValueError(f"unknown harvest filter field: {field_name}")
    if "source_actionability" not in available and filters.exclude_source_actionability:
        raise ValueError("unknown harvest filter field: source_actionability")


def _row_matches_filters(
    raw: Mapping[str, str],
    filters: HarvestFilters | None,
) -> bool:
    if filters is None or not filters.is_active():
        return True
    for field_name, allowed_values in filters.where.items():
        if (raw.get(field_name) or "").strip() not in set(allowed_values):
            return False
    if (
        (raw.get("source_actionability") or "").strip()
        in set(filters.exclude_source_actionability)
    ):
        return False
    return True


def _row_matches_filters_with_relaxed_field(
    raw: Mapping[str, str],
    filters: HarvestFilters,
    relaxed_field: str,
) -> bool:
    for field_name, allowed_values in filters.where.items():
        if field_name == relaxed_field:
            continue
        if (raw.get(field_name) or "").strip() not in set(allowed_values):
            return False
    if (
        (raw.get("source_actionability") or "").strip()
        in set(filters.exclude_source_actionability)
    ):
        return False
    return True


def _normalized_rebucket_fingerprint(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    fingerprint = {
        str(key): str(raw_value)
        for key, raw_value in value.items()
        if isinstance(raw_value, (str, int, float))
        and str(key)
        and str(raw_value)
    }
    return fingerprint or None


def _result_source_actionability_rebucket(
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    details = result.get("details")
    if not isinstance(details, Mapping):
        return None
    rebucket = details.get("source_actionability_rebucket")
    if not isinstance(rebucket, Mapping):
        return None
    remove_from = str(
        rebucket.get("remove_from") or rebucket.get("from") or ""
    ).strip()
    to_actionability = str(rebucket.get("to") or "").strip()
    if not remove_from or not to_actionability:
        return None
    parsed: dict[str, Any] = {
        "remove_from": remove_from,
        "to": to_actionability,
        "blocker": str(rebucket.get("blocker") or "").strip(),
        "reason": str(rebucket.get("reason") or "").strip(),
    }
    fingerprint = _normalized_rebucket_fingerprint(rebucket.get("fingerprint"))
    if fingerprint is not None:
        parsed["fingerprint"] = fingerprint
    return parsed


def _load_source_actionability_rebuckets(
    repo_root: Path,
    work_bucket: str,
) -> dict[str, dict[str, Any]]:
    harvest_dir = repo_root / "build" / "harvest"
    if not harvest_dir.is_dir():
        return {}

    ledgers = [
        path
        for path in harvest_dir.glob("*.json")
        if path.is_file()
    ]
    ledgers.sort(key=lambda path: (path.stat().st_mtime, path.name))

    rebuckets: dict[str, dict[str, Any]] = {}
    for path in ledgers:
        try:
            ledger = _read_harvest_ledger(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        ledger_bucket = str(ledger.get("work_bucket") or "")
        for raw_result in ledger["results"]:
            if not isinstance(raw_result, Mapping):
                continue
            function = str(raw_result.get("function") or "").strip()
            if not function:
                continue
            result_bucket = str(
                raw_result.get("work_bucket") or ledger_bucket or ""
            ).strip()
            if result_bucket != work_bucket:
                continue
            rebucket = _result_source_actionability_rebucket(raw_result)
            if rebucket is None:
                continue
            rebuckets[function] = rebucket
    return rebuckets


def _apply_source_actionability_rebucket(
    raw: Mapping[str, str],
    rebuckets: Mapping[str, Mapping[str, Any]],
    *,
    repo_root: Path,
    work_bucket: str,
) -> dict[str, str]:
    updated = {key: "" if value is None else value for key, value in raw.items()}
    function = (updated.get("function") or "").strip()
    if not function:
        return updated
    rebucket = rebuckets.get(function)
    if rebucket is None:
        return updated
    current_actionability = (updated.get("source_actionability") or "").strip()
    if current_actionability != rebucket.get("remove_from"):
        return updated
    rebucket_fingerprint = rebucket.get("fingerprint")
    if isinstance(rebucket_fingerprint, Mapping):
        current_fingerprint = _rebucket_fingerprint_from_raw(
            updated,
            repo_root=repo_root,
            work_bucket=work_bucket,
        )
        comparable_keys = {
            "source_sha256",
            "taxonomy_sha256",
            "row_tool_sha256",
            "tool_sha256",
        }
        for key, value in rebucket_fingerprint.items():
            if key not in comparable_keys:
                continue
            if not value:
                continue
            if current_fingerprint.get(str(key)) != str(value):
                return updated
    updated["source_actionability"] = str(rebucket.get("to") or "").strip()
    reason = str(rebucket.get("reason") or "").strip()
    blocker = str(rebucket.get("blocker") or "").strip()
    if reason:
        updated["actionability_reason"] = reason
    if blocker:
        updated["rebucket_blocker"] = blocker
    return updated


def _apply_terminal_attempt_overlay(
    raw: Mapping[str, str],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    repo_root: Path,
    work_bucket: str,
) -> dict[str, str]:
    if not evidence:
        return dict(raw)
    return apply_terminal_attempt_overlay(
        raw,
        evidence,
        current_tool_fingerprints=_rebucket_fingerprint_from_raw(
            raw,
            repo_root=repo_root,
            work_bucket=work_bucket,
        ),
    )


def _request_from_queue_row(
    raw: Mapping[str, str],
    *,
    work_bucket: str,
    repo_root: Path,
    match_percent: float,
    target_map: dict[str, dict[str, Any]] | None = None,
    apply: bool = False,
    timeout: int = 120,
    max_probes: int = 8,
) -> HarvestRequest:
    function = (raw.get("function") or "").strip()
    file_path = (raw.get("file_path") or "").strip()
    facts_by_function = target_map or {}
    return HarvestRequest(
        function=function,
        work_bucket=work_bucket,
        match_percent=match_percent,
        file_path=file_path,
        headline_tool=(raw.get("headline_tool") or "").strip(),
        source_file=resolve_source_file(repo_root, file_path),
        primary=(raw.get("primary") or "").strip(),
        subcategory=(raw.get("subcategory") or "").strip(),
        source_actionability=(raw.get("source_actionability") or "").strip(),
        frame_closability_tier=(
            raw.get("frame_closability_tier") or ""
        ).strip(),
        next_command=(raw.get("next_command") or "").strip(),
        frame_next_command=(raw.get("frame_next_command") or "").strip(),
        facts=dict(facts_by_function.get(function, {})),
        rebucket_fingerprint=_rebucket_fingerprint_from_raw(
            raw,
            repo_root=repo_root,
            work_bucket=work_bucket,
        ),
        terminal_attempt_status=(
            raw.get("terminal_attempt_status") or ""
        ).strip(),
        apply=apply,
        timeout=timeout,
        max_probes=max_probes,
    )


def assert_taxonomy_queue_is_completed(queue_path: Path) -> None:
    if queue_path.parent.name != "queues":
        return
    taxonomy_root = queue_path.parent.parent
    status_path = taxonomy_root / TAXONOMY_RUN_STATUS_FILENAME
    records_path = taxonomy_root / TAXONOMY_RECORDS_FILENAME
    is_taxonomy_artifact_root = records_path.exists()
    if not status_path.exists():
        if is_taxonomy_artifact_root:
            raise ValueError(
                f"taxonomy inventory status is missing for {taxonomy_root}; "
                "rerun tools/function_taxonomy_inventory.py before using queues"
            )
        return
    if not is_taxonomy_artifact_root:
        return
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"taxonomy inventory status is unreadable for {taxonomy_root}: {exc}"
        ) from exc
    if status.get("status") != "completed":
        detail = status.get("error") or status.get("started_at") or "unknown state"
        raise ValueError(
            f"taxonomy inventory has not completed for {taxonomy_root} "
            f"(status={status.get('status')!r}, detail={detail})"
        )


def load_queue_rows(
    queue_path: Path,
    *,
    work_bucket: str,
    repo_root: Path,
    min_match: float = 0.0,
    limit: int | None = None,
    target_map: dict[str, dict[str, Any]] | None = None,
    apply: bool = False,
    timeout: int = 120,
    max_probes: int = 8,
    filters: HarvestFilters | None = None,
    attempt_ledger_path: Path | None = None,
    include_terminal_attempts: bool = False,
) -> list[HarvestRequest]:
    rows: list[HarvestRequest] = []
    facts_by_function = target_map or {}
    source_actionability_rebuckets = _load_source_actionability_rebuckets(
        repo_root,
        work_bucket,
    )
    terminal_attempt_evidence = load_terminal_attempt_evidence(attempt_ledger_path)
    assert_taxonomy_queue_is_completed(queue_path)
    with queue_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        _validate_filter_fields(filters, reader.fieldnames)
        for raw_row in reader:
            raw = _apply_source_actionability_rebucket(
                raw_row,
                source_actionability_rebuckets,
                repo_root=repo_root,
                work_bucket=work_bucket,
            )
            raw = _apply_terminal_attempt_overlay(
                raw,
                terminal_attempt_evidence,
                repo_root=repo_root,
                work_bucket=work_bucket,
            )
            if (
                not include_terminal_attempts
                and is_active_terminal_attempt_row(raw)
            ):
                continue
            if not _row_matches_filters(raw, filters):
                continue
            if limit is not None and len(rows) >= limit:
                break
            match_percent = _float_or_none(raw.get("match_percent")) or 0.0
            if match_percent < min_match:
                continue
            function = (raw.get("function") or "").strip()
            if not function:
                continue
            rows.append(
                _request_from_queue_row(
                    raw,
                    work_bucket=work_bucket,
                    repo_root=repo_root,
                    match_percent=match_percent,
                    target_map=facts_by_function,
                    apply=apply,
                    timeout=timeout,
                    max_probes=max_probes,
                )
            )
    return rows


def _top_facet_values(
    rows: list[Mapping[str, str]],
    field_name: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for raw in rows:
        value = (raw.get(field_name) or "").strip()
        if value:
            counts[value] += 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    ]


def _preview_sample_entry(request: HarvestRequest) -> dict[str, Any]:
    return {
        "function": request.function,
        "match_percent": request.match_percent,
        "file_path": request.file_path,
        "primary": request.primary,
        "subcategory": request.subcategory,
        "source_actionability": request.source_actionability,
        "headline_tool": request.headline_tool,
        "frame_closability_tier": request.frame_closability_tier,
        "next_command": request.next_command,
        "frame_next_command": request.frame_next_command,
        "terminal_attempt_status": request.terminal_attempt_status,
        "harness": select_harness(request),
    }


def preview_harvest_queue(
    queue_path: Path,
    *,
    work_bucket: str,
    repo_root: Path,
    min_match: float = 0.0,
    limit: int | None = None,
    target_map: dict[str, dict[str, Any]] | None = None,
    target_map_path: Path | None = None,
    filters: HarvestFilters | None = None,
    sample_limit: int = 10,
    facet_limit: int = 8,
    attempt_ledger_path: Path | None = None,
    include_terminal_attempts: bool = False,
) -> dict[str, Any]:
    if target_map is None:
        target_map = load_target_map(target_map_path)
    sample_limit = max(0, sample_limit)
    facet_limit = max(0, facet_limit)
    queue_rows = 0
    eligible_rows: list[dict[str, str]] = []
    matching_rows: list[dict[str, str]] = []
    terminal_attempt_rows: list[dict[str, str]] = []
    sample: list[dict[str, Any]] = []
    source_actionability_rebuckets = _load_source_actionability_rebuckets(
        repo_root,
        work_bucket,
    )
    terminal_attempt_evidence = load_terminal_attempt_evidence(attempt_ledger_path)

    assert_taxonomy_queue_is_completed(queue_path)
    with queue_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        _validate_filter_fields(filters, reader.fieldnames)
        for raw_row in reader:
            raw = _apply_source_actionability_rebucket(
                raw_row,
                source_actionability_rebuckets,
                repo_root=repo_root,
                work_bucket=work_bucket,
            )
            raw = _apply_terminal_attempt_overlay(
                raw,
                terminal_attempt_evidence,
                repo_root=repo_root,
                work_bucket=work_bucket,
            )
            function = (raw.get("function") or "").strip()
            if not function:
                continue
            queue_rows += 1
            match_percent = _float_or_none(raw.get("match_percent")) or 0.0
            if match_percent < min_match:
                continue
            if is_active_terminal_attempt_row(raw):
                terminal_attempt_rows.append(raw)
                if not include_terminal_attempts:
                    continue
            eligible_rows.append(raw)
            if not _row_matches_filters(raw, filters):
                continue
            matching_rows.append(raw)
            if len(sample) < sample_limit:
                request = _request_from_queue_row(
                    raw,
                    work_bucket=work_bucket,
                    repo_root=repo_root,
                    match_percent=match_percent,
                    target_map=target_map,
                )
                sample.append(_preview_sample_entry(request))

    matching_count = len(matching_rows)
    if limit is None:
        would_process_rows = matching_count
    else:
        would_process_rows = min(matching_count, max(0, limit))
    facet_rows = matching_rows if matching_rows else eligible_rows
    facets = {
        field_name: _top_facet_values(facet_rows, field_name, limit=facet_limit)
        for field_name in PREVIEW_FACET_FIELDS
    }
    terminal_attempt_facets = {
        field_name: _top_facet_values(
            terminal_attempt_rows,
            field_name,
            limit=facet_limit,
        )
        for field_name in TERMINAL_ATTEMPT_FACET_FIELDS
    }
    near_miss_facets: dict[str, list[dict[str, Any]]] = {}
    if filters is not None and filters.where:
        for field_name in sorted(filters.where):
            near_miss_rows = [
                raw
                for raw in eligible_rows
                if raw not in matching_rows
                and _row_matches_filters_with_relaxed_field(
                    raw,
                    filters,
                    field_name,
                )
            ]
            near_miss_facets[field_name] = _top_facet_values(
                near_miss_rows,
                field_name,
                limit=facet_limit,
            )
        name_magic_blocker_rows = [
            raw
            for raw in eligible_rows
            if raw not in matching_rows
            and (raw.get("name_magic_blocker") or "").strip()
        ]
        if name_magic_blocker_rows:
            near_miss_facets["name_magic_blocker"] = _top_facet_values(
                name_magic_blocker_rows,
                "name_magic_blocker",
                limit=facet_limit,
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "work_bucket": work_bucket,
        "taxonomy_queue": str(queue_path),
        "target_map": str(target_map_path) if target_map_path else None,
        "min_match": min_match,
        "limit": limit,
        "filters": filters.to_dict() if filters is not None else None,
        "counts": {
            "queue_rows": queue_rows,
            "eligible_rows": len(eligible_rows),
            "matching_rows": matching_count,
            "would_process_rows": would_process_rows,
            "terminal_attempt_rows": len(terminal_attempt_rows),
        },
        "facet_source": "matching_rows" if matching_rows else "eligible_rows",
        "facets": facets,
        "terminal_attempt_facets": terminal_attempt_facets,
        "near_miss_facets": near_miss_facets,
        "sample": sample,
    }


def _extract_registered_harness(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    lowered = text.strip().lower()
    if lowered in REGISTERED_HARNESSES:
        return lowered
    for harness in REGISTERED_HARNESSES:
        if harness in lowered:
            return harness
    return None


def _contains_debug_dump_local(value: str) -> bool:
    return "debug dump local" in value.lower()


def _is_allocator_pcdump_triage_request(request: HarvestRequest) -> bool:
    if request.work_bucket != "register-allocator":
        return False
    return (
        request.source_actionability == "pcdump-proof-needed"
        or request.headline_tool == "mwcc-debug"
        or _contains_debug_dump_local(request.next_command)
        or _contains_debug_dump_local(request.frame_next_command)
    )


def _is_exhausted_allocator_rebucket_request(request: HarvestRequest) -> bool:
    if request.work_bucket != "register-allocator":
        return False
    if request.source_actionability not in {
        BLOCKER_ALLOCATOR_SOURCE_LIFETIME,
        BLOCKER_ALLOCATOR_TARGET_VECTOR,
        ALLOCATOR_TARGET_CONFLICT_ACTIONABILITY,
    }:
        return False
    return (
        request.headline_tool == "mwcc-debug"
        or _contains_debug_dump_local(request.next_command)
        or _contains_debug_dump_local(request.frame_next_command)
    )


def _is_exhausted_frame_transform_rebucket_request(request: HarvestRequest) -> bool:
    if request.work_bucket != "stack-local-layout":
        return False
    if request.source_actionability not in {
        FRAME_TRANSFORM_DIAGNOSTIC_ACTIONABILITY,
        FRAME_TRANSFORM_SOURCE_PROBE_ACTIONABILITY,
    }:
        return False
    return (
        request.headline_tool == HARNESS_FRAME_TRANSFORM
        or request.frame_closability_tier == "current-tools-padstack"
        or HARNESS_FRAME_TRANSFORM in request.next_command
        or HARNESS_FRAME_TRANSFORM in request.frame_next_command
    )


def _is_blocked_data_symbol_request(request: HarvestRequest) -> bool:
    return (
        request.source_actionability in DATA_SYMBOL_BLOCKED_SOURCE_ACTIONABILITIES
        or request.source_actionability.startswith("blocked-data-symbol-")
    )


def select_harness(request: HarvestRequest) -> str | None:
    if request.terminal_attempt_status == "active":
        return None

    if request.source_actionability in {
        "source-ceiling",
        "tooling-blocked",
        "manual-review",
    }:
        return None

    explicit_harness = request.facts.get("harness")
    if explicit_harness:
        harness = str(explicit_harness).strip().lower()
        return harness if harness in REGISTERED_HARNESSES else None

    if _is_blocked_data_symbol_request(request):
        return None

    if request.source_actionability == MALFORMED_SOURCE_CANDIDATE_ACTIONABILITY:
        return None

    if _is_exhausted_allocator_rebucket_request(request):
        return None

    if _is_allocator_pcdump_triage_request(request):
        return HARNESS_ALLOCATOR_PCDUMP_TRIAGE

    if request.primary == "data-symbol-relocation":
        return HARNESS_NAME_MAGIC_SOURCE
    if request.work_bucket == "data-symbol-relocation" and (
        request.primary == "data-symbol-or-relocation"
        or request.subcategory == "persistent-data-symbol-or-relocation"
        or request.source_actionability == "current-tools-data-symbol"
        or request.headline_tool == "checkdiff-name-magic"
    ):
        return HARNESS_NAME_MAGIC_SOURCE

    if request.primary == "control-flow-source-shape":
        return HARNESS_CONTROL_FLOW_SHAPE
    if request.primary == "indexed-struct-pointer-materialization":
        return HARNESS_INDEXED_STRUCT
    if request.source_actionability == "current-tools-indexed-pointer":
        return HARNESS_INDEXED_STRUCT
    if request.work_bucket == "stack-local-layout" and (
        request.headline_tool == HARNESS_LIFETIME_LAYOUT
        or HARNESS_LIFETIME_LAYOUT in request.next_command
        or HARNESS_LIFETIME_LAYOUT in request.frame_next_command
        or (
            request.source_actionability == "source-probe"
            and request.subcategory == "same-frame-stack-slot-placement"
        )
    ):
        return HARNESS_LIFETIME_LAYOUT

    if _is_exhausted_frame_transform_rebucket_request(request):
        return None

    for value in (
        request.headline_tool,
        request.source_actionability,
        request.frame_closability_tier,
        request.next_command,
        request.frame_next_command,
    ):
        harness = _extract_registered_harness(value)
        if harness is not None:
            if harness == HARNESS_ALLOCATOR_PCDUMP_TRIAGE:
                if _is_allocator_pcdump_triage_request(request):
                    return harness
                continue
            return harness

    if request.frame_closability_tier == "current-tools-padstack":
        return HARNESS_FRAME_TRANSFORM
    if (
        request.subcategory == "branch-or-control-flow-shape"
        and (
            request.work_bucket == "structural-reconstruction"
            or request.primary == "structural-reconstruction"
        )
    ):
        return HARNESS_CONTROL_FLOW_SHAPE
    return None


def extract_candidate_score(candidate: dict[str, Any]) -> float | None:
    for key in ("final_match_percent", "match_percent"):
        score = _float_or_none(candidate.get(key))
        if score is not None:
            return score
    objective = candidate.get("objective")
    if isinstance(objective, dict):
        return _float_or_none(objective.get("match_percent"))
    return None


def _is_c_source_path(value: str) -> bool:
    return Path(value).suffix == ".c"


def _candidate_source_path_any(candidate: dict[str, Any]) -> str | None:
    for key in (
        "source_path",
        "source_retained",
        "retained_source_path",
        "candidate_source_path",
        "generated_source_path",
        "retained_source",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value
    value = candidate.get("path")
    if isinstance(value, str) and value:
        return value
    source = candidate.get("source")
    if isinstance(source, dict):
        value = source.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _candidate_source_path(candidate: dict[str, Any]) -> str | None:
    value = _candidate_source_path_any(candidate)
    if value is not None and _is_c_source_path(value):
        return value
    return None


def _candidate_header_path(candidate: Mapping[str, Any] | None) -> str | None:
    if candidate is None:
        return None
    for key in (
        "header_path",
        "header_retained",
        "retained_header_path",
        "candidate_header_path",
        "generated_header_path",
        "retained_header",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value
    header = candidate.get("header")
    if isinstance(header, Mapping):
        value = header.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _candidate_header_target(
    candidate: Mapping[str, Any] | None,
    request: HarvestRequest,
    repo_root: Path,
) -> Path | None:
    if candidate is not None:
        value = candidate.get("header_target")
        if isinstance(value, str) and value:
            return _candidate_path_for_apply(value, repo_root)
    if request.source_file is None:
        return None
    return request.source_file.with_suffix(".h")


def _iter_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "variants",
        "ranked_variants",
        "candidates",
        "ranked_candidates",
        "results",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        return [candidate]
    if (
        _candidate_source_path(payload) is not None
        and extract_candidate_score(payload) is not None
    ):
        return [payload]
    return []


def best_validated_candidate(payload: Any) -> dict[str, Any] | None:
    for candidate in _iter_candidates(payload):
        if candidate.get("status") != "ok":
            continue
        if _candidate_source_path(candidate) is None:
            continue
        score = extract_candidate_score(candidate)
        if score is None:
            continue
        if abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON:
            return candidate
    return None


def _candidate_delta(candidate: dict[str, Any]) -> float | None:
    for key in ("delta_match_percent", "delta", "match_delta"):
        delta = _float_or_none(candidate.get(key))
        if delta is not None:
            return delta
    objective = candidate.get("objective")
    if isinstance(objective, dict):
        for key in ("delta_match_percent", "delta", "match_delta"):
            delta = _float_or_none(objective.get(key))
            if delta is not None:
                return delta
    return None


def _candidate_detail(candidate: dict[str, Any]) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for key in (
        "label",
        "operator",
        "status",
        "reason",
        "blocker",
        "final_match_percent",
        "match_percent",
        "match_pct",
        "score",
        "no_name_magic_match",
        "match_percent_error",
        "error",
    ):
        value = candidate.get(key)
        if value is not None:
            detail[key] = value
    source_path = _candidate_source_path_any(candidate)
    if source_path is not None:
        detail["source_path"] = source_path
    score = extract_candidate_score(candidate)
    if score is not None:
        detail["score_percent"] = score
    delta = _candidate_delta(candidate)
    if delta is not None:
        detail["delta_match_percent"] = delta
    return detail


def _candidate_omits_target_function(candidate: dict[str, Any]) -> bool:
    status = str(candidate.get("status") or "")
    if status == "malformed-source":
        return True
    error = str(candidate.get("error") or candidate.get("match_percent_error") or "")
    if "not found in pcdump" not in error:
        return False
    return _candidate_source_path_any(candidate) is not None


def _malformed_source_candidate_detail(payload: Any) -> dict[str, Any] | None:
    for candidate in _iter_candidates(payload):
        if _candidate_omits_target_function(candidate):
            return _candidate_detail(candidate)
    return None


def best_scored_candidate(payload: Any) -> dict[str, Any] | None:
    scored = [
        candidate
        for candidate in _iter_candidates(payload)
        if extract_candidate_score(candidate) is not None
    ]
    if not scored:
        return None
    return max(
        scored,
        key=lambda candidate: extract_candidate_score(candidate) or 0.0,
    )


def no_validated_candidate_details(payload: Any) -> dict[str, Any]:
    candidates = _iter_candidates(payload)
    details: dict[str, Any] = {"candidate_count": len(candidates)}
    scored_count = sum(
        1
        for candidate in candidates
        if extract_candidate_score(candidate) is not None
    )
    if candidates:
        details["scored_candidate_count"] = scored_count
        details["unscored_candidate_count"] = len(candidates) - scored_count
    best_candidate = best_scored_candidate(payload)
    if best_candidate is not None:
        details["best_candidate"] = _candidate_detail(best_candidate)
    elif candidates:
        details["unscored_candidate"] = _candidate_detail(candidates[0])
    malformed_candidate = _malformed_source_candidate_detail(payload)
    if malformed_candidate is not None:
        details["malformed_source_candidate"] = malformed_candidate
    return details


def _has_source_emitting_no_name_magic_candidate(payload: Any) -> bool:
    for candidate in _iter_candidates(payload):
        if extract_candidate_score(candidate) is None:
            continue
        if _candidate_source_path_any(candidate) is None:
            continue
        if candidate.get("no_name_magic_match") is True:
            continue
        return True
    return False


def _name_magic_source_stop_kind(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    stop = payload.get("stop_condition")
    if not isinstance(stop, dict):
        return None
    kind = stop.get("kind")
    return kind if isinstance(kind, str) else None


def _name_magic_candidate_score(candidate: dict[str, Any]) -> float | None:
    for key in ("final_match_percent", "match_percent"):
        score = _float_or_none(candidate.get(key))
        if score is not None:
            return score
    return None


def _is_valid_name_magic_candidate(candidate: dict[str, Any]) -> bool:
    if candidate.get("status") != "ok":
        return False
    if candidate.get("no_name_magic_match") is not True:
        return False
    score = _name_magic_candidate_score(candidate)
    if score is None:
        return False
    return abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON


def best_validated_name_magic_candidate(
    payload: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    if _name_magic_source_stop_kind(payload) != "validated":
        return None, None
    for candidate in _iter_candidates(payload):
        if not _is_valid_name_magic_candidate(candidate):
            continue
        candidate_path = _candidate_source_path(candidate)
        if candidate_path is not None:
            return candidate, None
        raw_path = _candidate_source_path_any(candidate)
        if raw_path is not None and not _is_c_source_path(raw_path):
            return None, raw_path
    return None, None


def _default_runner(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [sys.executable, "-m", "src.cli", *args]
    try:
        completed = _run_with_process_group_timeout(
            command,
            cwd=cwd,
            timeout=timeout + 30,
            env=_env_with_child_hang_timeout(timeout),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = "" if exc.output is None else str(exc.output)
        stderr = "" if exc.stderr is None else str(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"harvest subprocess timed out after {timeout + 30}s"
        return HarnessProcessResult(
            command=list(args),
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )
    return HarnessProcessResult(
        command=list(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _command_report(
    command: list[str],
    process: HarnessProcessResult,
) -> dict[str, Any]:
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": _short_output(process.stdout),
        "stderr": _short_output(process.stderr),
    }


def _process_reports_unsafe_local_pcdump(process: HarnessProcessResult) -> bool:
    if process.returncode not in {124, 125}:
        return False
    output = f"{process.stderr}\n{process.stdout}".lower()
    return (
        "unsafe local pcdump lane" in output
        or "unsafe local mwcc-debug lane" in output
        or "uninterruptible wibo" in output
    )


def _pcdump_unit_for_source(repo_root: Path, source_file: Path) -> str:
    try:
        rel = source_file.resolve().relative_to((repo_root / "src").resolve())
    except ValueError as exc:
        raise ValueError(
            f"pcdump preflight source is not under repo src/: {source_file}"
        ) from exc
    if rel.suffix != ".c":
        raise ValueError(f"pcdump preflight expected .c source: {source_file}")
    return rel.with_suffix("").as_posix()


def _source_rel_for_local_pcdump_guard(repo_root: Path, source_file: Path) -> str:
    try:
        rel = source_file.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return source_file.as_posix()
    return rel.as_posix()


def _needs_pcdump_preflight(
    request: HarvestRequest,
    *,
    compose: bool,
) -> bool:
    if request.source_file is None:
        return False
    harness = select_harness(request)
    if harness == HARNESS_ALLOCATOR_PCDUMP_TRIAGE:
        return True
    if harness == HARNESS_INDEXED_STRUCT:
        return True
    lifetime_layout_source_probe = request.work_bucket == "stack-local-layout" and (
        request.headline_tool == HARNESS_LIFETIME_LAYOUT
        or HARNESS_LIFETIME_LAYOUT in request.next_command
        or HARNESS_LIFETIME_LAYOUT in request.frame_next_command
        or (
            request.source_actionability == "source-probe"
            and request.subcategory == "same-frame-stack-slot-placement"
        )
    )
    if harness == HARNESS_LIFETIME_LAYOUT:
        return lifetime_layout_source_probe
    frame_transform_current_tools = (
        request.source_actionability == "current-tools"
        and request.frame_closability_tier == "current-tools-padstack"
    )
    if frame_transform_current_tools and harness == HARNESS_FRAME_TRANSFORM:
        return True
    if compose:
        layer_harnesses = {
            str(layer.get("harness") or "").strip().lower()
            for layer in _normalize_layer_sequence(request)
        }
        return (
            HARNESS_FRAME_TRANSFORM in layer_harnesses
            and frame_transform_current_tools
        ) or (
            HARNESS_LIFETIME_LAYOUT in layer_harnesses
            and lifetime_layout_source_probe
        ) or (
            HARNESS_INDEXED_STRUCT in layer_harnesses
        ) or (HARNESS_ALLOCATOR_PCDUMP_TRIAGE in layer_harnesses)
    return False


def _requires_pcdump_setup_preflight(
    request: HarvestRequest,
    *,
    compose: bool,
) -> bool:
    if select_harness(request) == HARNESS_INDEXED_STRUCT:
        return True
    if not compose:
        return False
    layer_harnesses = {
        str(layer.get("harness") or "").strip().lower()
        for layer in _normalize_layer_sequence(request)
    }
    return HARNESS_INDEXED_STRUCT in layer_harnesses


def _run_pcdump_preflight(
    requests: list[HarvestRequest],
    *,
    repo_root: Path,
    runner: HarnessRunner,
    timeout: int,
    compose: bool,
) -> PcdumpPreflightReport:
    by_unit: dict[str, HarvestRequest] = {}
    for request in requests:
        if not _needs_pcdump_preflight(request, compose=compose):
            continue
        assert request.source_file is not None
        unit = _pcdump_unit_for_source(repo_root, request.source_file)
        by_unit.setdefault(unit, request)

    if not by_unit:
        return PcdumpPreflightReport(enabled=False)

    report = PcdumpPreflightReport(
        enabled=True,
        required_units=list(by_unit),
    )
    allow_unsafe = local_safety.allow_unsafe_local_pcdump()
    observed_processes = (
        []
        if allow_unsafe
        else local_safety.scan_local_wibo_processes()
    )
    safe_by_unit: dict[str, HarvestRequest] = {}
    seen_unsafe_pids: set[int] = set()
    for unit, request in by_unit.items():
        assert request.source_file is not None
        source_rel = _source_rel_for_local_pcdump_guard(repo_root, request.source_file)
        guard = local_safety.guard_local_pcdump_lane(
            source_rel=source_rel,
            function=request.function,
            processes=observed_processes,
            allow_unsafe=allow_unsafe,
        )
        if guard.unsafe:
            report.unsafe_units.append(unit)
            report.unsafe_sources.append(source_rel)
            for process in guard.processes:
                if process.pid in seen_unsafe_pids:
                    continue
                seen_unsafe_pids.add(process.pid)
                report.unsafe_processes.append(process.to_dict())
            continue
        safe_by_unit[unit] = request

    if not safe_by_unit:
        return report

    setup_required = any(
        _requires_pcdump_setup_preflight(request, compose=compose)
        for request in safe_by_unit.values()
    )
    units_to_generate: list[str] = []
    for unit, request in safe_by_unit.items():
        entry = pcdump_cache.lookup(repo_root, unit)
        if entry is None:
            report.missing_units.append(unit)
            units_to_generate.append(unit)
        elif entry.fresh:
            report.fresh_units.append(unit)
        else:
            report.stale_units.append(unit)
            units_to_generate.append(unit)

    if not units_to_generate and not setup_required:
        return report

    setup_command = ["debug", "dump", "setup"]
    try:
        setup_process = runner(
            setup_command,
            cwd=repo_root / "tools" / "melee-agent",
            timeout=timeout,
        )
    except Exception as exc:
        raise ValueError(f"pcdump preflight setup failed to run: {exc}") from exc
    report.setup_command = _command_report(setup_command, setup_process)
    if setup_process.returncode != 0:
        raise ValueError(
            "pcdump preflight setup failed: "
            f"{_short_output(setup_process.stderr or setup_process.stdout)}"
        )

    if not units_to_generate:
        return report

    for unit in units_to_generate:
        request = safe_by_unit[unit]
        assert request.source_file is not None
        dump_command = [
            "debug",
            "dump",
            "local",
            str(request.source_file),
            "--function",
            request.function,
        ]
        try:
            dump_process = runner(
                dump_command,
                cwd=repo_root / "tools" / "melee-agent",
                timeout=timeout,
            )
        except Exception as exc:
            report.dump_failures.append({
                "unit": unit,
                "command": dump_command,
                "error": str(exc),
            })
            entry = pcdump_cache.lookup(repo_root, unit)
            if entry is not None and entry.fresh:
                report.generated_units.append(unit)
            else:
                report.failed_units.append(unit)
            continue
        report.dump_commands.append(_command_report(dump_command, dump_process))
        if dump_process.returncode != 0:
            failure = _command_report(dump_command, dump_process)
            failure["unit"] = unit
            report.dump_failures.append(failure)
            if _process_reports_unsafe_local_pcdump(dump_process):
                if unit not in report.unsafe_units:
                    report.unsafe_units.append(unit)
                source_rel = _source_rel_for_local_pcdump_guard(
                    repo_root,
                    request.source_file,
                )
                if source_rel not in report.unsafe_sources:
                    report.unsafe_sources.append(source_rel)
                continue
            entry = pcdump_cache.lookup(repo_root, unit)
            if entry is not None and entry.fresh:
                report.generated_units.append(unit)
            else:
                report.failed_units.append(unit)
            continue
        report.generated_units.append(unit)
    return report


def _default_validator(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [sys.executable, "tools/checkdiff.py", function, "--compact"]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_match_checker(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_no_name_magic_validator(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--compact",
        "--no-name-magic",
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_no_name_magic_match_checker(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
        "--no-name-magic",
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _frame_transform_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_FRAME_TRANSFORM,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _coalesce_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        HARNESS_COALESCE,
        "-f",
        request.function,
        "--target",
        str(request.facts["target"]),
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _select_order_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        HARNESS_SELECT_ORDER,
        "-f",
        request.function,
        "--target",
        str(request.facts["target"]),
        "--class",
        str(request.facts.get("class_id", 0)),
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _indexed_struct_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_INDEXED_STRUCT,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _name_magic_source_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_NAME_MAGIC_SOURCE,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _control_flow_shape_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_CONTROL_FLOW_SHAPE,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _lifetime_layout_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_LIFETIME_LAYOUT,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _allocator_pcdump_triage_command(request: HarvestRequest) -> list[str]:
    return [
        "debug",
        "target",
        "match-iter-first",
        "-f",
        request.function,
        "--regs",
        ALLOCATOR_PCDUMP_TRIAGE_REGS,
        "--force-vector",
        "auto",
        "--json",
    ]


def _base_result(
    request: HarvestRequest,
    *,
    harness: str | None,
    status: str,
    blocker: str | None,
    reason: str,
    command: list[str] | None = None,
    candidate_path: str | None = None,
    final_match_percent: float | None = None,
    applied: bool = False,
    details: dict[str, Any] | None = None,
    source_actionability: str | None = None,
) -> HarvestResult:
    return HarvestResult(
        function=request.function,
        work_bucket=request.work_bucket,
        headline_tool=request.headline_tool,
        status=status,
        blocker=blocker,
        reason=reason,
        command=command or [],
        candidate_path=candidate_path,
        source_file=str(request.source_file) if request.source_file else None,
        final_match_percent=final_match_percent,
        applied=applied,
        details=details or {},
        harness=harness,
        primary=request.primary,
        subcategory=request.subcategory,
        source_actionability=source_actionability or request.source_actionability,
        frame_closability_tier=request.frame_closability_tier,
    )


def _unsafe_local_pcdump_result(
    request: HarvestRequest,
    *,
    repo_root: Path,
    preflight_report: PcdumpPreflightReport,
) -> HarvestResult | None:
    if request.source_file is None:
        return None
    try:
        unit = _pcdump_unit_for_source(repo_root, request.source_file)
    except ValueError:
        return None
    if unit not in set(preflight_report.unsafe_units):
        return None
    source_rel = _source_rel_for_local_pcdump_guard(repo_root, request.source_file)
    source_aliases = {source_rel, source_rel.removeprefix("src/")}
    matching_processes = [
        process
        for process in preflight_report.unsafe_processes
        if process.get("source_rel") in source_aliases
    ]
    return _base_result(
        request,
        harness=select_harness(request),
        status="blocked",
        blocker=BLOCKER_UNSAFE_LOCAL_PCDUMP_LANE,
        reason=(
            f"uninterruptible wibo process already exists for {source_rel}; "
            "local pcdump lane marked unsafe and candidate scoring was skipped"
        ),
        details={
            "unit": unit,
            "source_rel": source_rel,
            "unsafe_processes": matching_processes or preflight_report.unsafe_processes,
        },
    )


def _short_output(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _match_checker_indicates_match(process: HarnessProcessResult) -> bool:
    if process.returncode != 0:
        return False
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and "match" in payload:
        return payload.get("match") is True
    return True


def _strict_match_payload(process: HarnessProcessResult) -> dict[str, Any] | None:
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _strict_payload_indicates_match(payload: Mapping[str, Any] | None) -> bool:
    return payload is not None and payload.get("match") is True


def _payload_match_percent(payload: Mapping[str, Any] | None) -> float | None:
    if payload is None:
        return None
    for key in ("fuzzy_match_percent", "match_percent", "final_match_percent"):
        score = _float_or_none(payload.get(key))
        if score is not None:
            return score
    objective = payload.get("objective")
    if isinstance(objective, Mapping):
        return _float_or_none(objective.get("match_percent"))
    return None


def _payload_classification(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if payload is None:
        return {}
    classification = payload.get("classification")
    return classification if isinstance(classification, Mapping) else {}


def _payload_classification_primary(payload: Mapping[str, Any] | None) -> str:
    primary = _payload_classification(payload).get("primary")
    return str(primary) if isinstance(primary, str) else ""


def _classification_has_layer_signal(
    payload: Mapping[str, Any] | None,
    harness: str,
) -> bool:
    classification = _payload_classification(payload)
    primary = _payload_classification_primary(payload)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return (
            primary in {"data-symbol-or-relocation", "data-symbol-relocation"}
            or "data-symbol" in primary
        )
    if harness == HARNESS_INDEXED_STRUCT:
        return (
            primary == "indexed-struct-pointer-materialization"
            or "indexed_struct_pointer_materialization" in classification
            or "indexed-struct" in primary
        )
    if harness == HARNESS_FRAME_TRANSFORM:
        return (
            "stack" in primary
            or "frame" in primary
            or "stack_frame_delta" in classification
            or "stack_slot_layout_cause" in classification
            or "stack_slot_localizer" in classification
        )
    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER}:
        return "register" in primary
    return False


def _payload_verifies_layer_improvement(
    before_payload: Mapping[str, Any] | None,
    after_payload: Mapping[str, Any] | None,
    *,
    harness: str,
) -> bool:
    if _strict_payload_indicates_match(after_payload):
        return True
    if after_payload is None:
        return False
    before_score = _payload_match_percent(before_payload)
    after_score = _payload_match_percent(after_payload)
    if (
        before_score is not None
        and after_score is not None
        and after_score > before_score + VALIDATED_EPSILON
    ):
        return True
    return _classification_has_layer_signal(
        before_payload,
        harness,
    ) and not _classification_has_layer_signal(after_payload, harness)


def _harness_blocker_result(payload: Any) -> tuple[str, str, str] | None:
    if not isinstance(payload, dict):
        return None
    if _malformed_source_candidate_detail(payload) is not None:
        return (
            "blocked",
            BLOCKER_MALFORMED_SOURCE_CANDIDATE,
            "generated source candidate did not preserve the requested function",
        )
    blocker = payload.get("blocker")
    stop = payload.get("stop_condition")
    reason = None
    kind = "no_match"
    if isinstance(stop, dict):
        blocker = blocker or stop.get("blocker")
        reason = stop.get("reason")
        stop_kind = stop.get("kind")
        if stop_kind == "blocked":
            kind = "blocked"
        elif stop_kind == "unvalidated":
            kind = "no_match"
    if isinstance(blocker, str) and blocker:
        return kind, blocker, str(reason or blocker)
    return None


def _malformed_source_rebucket(
    request: HarvestRequest,
    *,
    harness: str,
    blocker: str,
    details: dict[str, Any],
) -> str | None:
    if blocker != BLOCKER_MALFORMED_SOURCE_CANDIDATE:
        return None
    rebucketable_source_actionabilities = {
        HARNESS_INDEXED_STRUCT: "current-tools-indexed-pointer",
        HARNESS_LIFETIME_LAYOUT: "source-probe",
    }
    remove_from = rebucketable_source_actionabilities.get(harness)
    if remove_from is None or request.source_actionability != remove_from:
        return None
    details["source_actionability_rebucket"] = {
        "from": request.source_actionability,
        "to": MALFORMED_SOURCE_CANDIDATE_ACTIONABILITY,
        "remove_from": remove_from,
        "blocker": blocker,
        "reason": "candidate pcdump omitted the requested function",
    }
    return MALFORMED_SOURCE_CANDIDATE_ACTIONABILITY


def _no_name_magic_candidate_rebucket(
    request: HarvestRequest,
    *,
    harness: str,
    blocker: str,
    details: dict[str, Any],
    payload: Any,
) -> str | None:
    if harness != HARNESS_NAME_MAGIC_SOURCE:
        return None
    if blocker != BLOCKER_NO_NAME_MAGIC_CANDIDATE:
        return None
    remove_from = "current-tools-data-symbol"
    if request.source_actionability != remove_from:
        return None
    scored_candidate_count = _float_or_none(details.get("scored_candidate_count"))
    if scored_candidate_count is None or scored_candidate_count <= 0:
        return None
    if not _has_source_emitting_no_name_magic_candidate(payload):
        return None
    details["source_actionability_rebucket"] = {
        "from": request.source_actionability,
        "to": DATA_SYMBOL_NO_NAME_MAGIC_CANDIDATE_ACTIONABILITY,
        "remove_from": remove_from,
        "blocker": blocker,
        "reason": "no scored source candidate reached a true --no-name-magic match",
        "fingerprint": _rebucket_fingerprint_from_request(request),
    }
    return DATA_SYMBOL_NO_NAME_MAGIC_CANDIDATE_ACTIONABILITY


def _allocator_force_vector_no_match_rebucket(
    request: HarvestRequest,
    *,
    payload: Mapping[str, Any],
    details: dict[str, Any],
) -> str | None:
    remove_from = "pcdump-proof-needed"
    if request.work_bucket != "register-allocator":
        return None
    if request.source_actionability != remove_from:
        return None
    actionability = payload.get("target_vector_actionability")
    status = ""
    if isinstance(actionability, Mapping):
        status = str(actionability.get("status") or "").strip()

    if status == "already-satisfied":
        to_actionability = BLOCKER_ALLOCATOR_SOURCE_LIFETIME
        reason = (
            "force-vector probes did not match and target vector is already "
            "satisfied; pivot to source lifetime/callee-save shape"
        )
    elif (
        payload.get("force_vector_runnable") is False
        or payload.get("force_vector_recommended") is False
        or _has_force_vector_conflicts(payload.get("force_vector_conflicts"))
    ):
        to_actionability = ALLOCATOR_TARGET_CONFLICT_ACTIONABILITY
        reason = (
            "force-vector probes did not match and target-vector override "
            "conflicts or is not runnable"
        )
    elif status == "needs-move":
        to_actionability = BLOCKER_ALLOCATOR_TARGET_VECTOR
        reason = (
            "force-vector probes did not match; target-vector movement remains "
            "the next allocator lever"
        )
    else:
        return None

    details["source_actionability_rebucket"] = {
        "from": request.source_actionability,
        "to": to_actionability,
        "remove_from": remove_from,
        "blocker": BLOCKER_ALLOCATOR_FORCE_VECTOR_NO_MATCH,
        "reason": reason,
        "fingerprint": _rebucket_fingerprint_from_request(request),
    }
    return to_actionability


def _is_padstack_diagnostic_candidate(candidate: Mapping[str, Any]) -> bool:
    label = str(candidate.get("label") or "").strip().lower()
    operator = str(candidate.get("operator") or "").strip().lower()
    combined = f"{label} {operator}".replace("_", "-")
    return "pad-stack" in combined or "padstack" in combined


def _frame_transform_no_validated_rebucket(
    request: HarvestRequest,
    *,
    harness: str,
    blocker: str,
    details: dict[str, Any],
) -> str | None:
    if harness != HARNESS_FRAME_TRANSFORM:
        return None
    if blocker != BLOCKER_NO_VALIDATED_CANDIDATE:
        return None
    if request.work_bucket != "stack-local-layout":
        return None
    remove_from = "current-tools"
    if request.source_actionability != remove_from:
        return None
    if request.frame_closability_tier != "current-tools-padstack":
        return None
    scored_candidate_count = _float_or_none(details.get("scored_candidate_count"))
    if scored_candidate_count is None or scored_candidate_count <= 0:
        return None
    best_candidate = details.get("best_candidate")
    if not isinstance(best_candidate, Mapping):
        return None
    if _is_padstack_diagnostic_candidate(best_candidate):
        to_actionability = FRAME_TRANSFORM_DIAGNOSTIC_ACTIONABILITY
        reason = (
            "frame-transform scored PAD_STACK diagnostic candidates but no "
            "validated 100% source"
        )
    else:
        to_actionability = FRAME_TRANSFORM_SOURCE_PROBE_ACTIONABILITY
        reason = (
            "frame-transform scored source-shape candidates but no validated "
            "100% source"
        )

    details["source_actionability_rebucket"] = {
        "from": request.source_actionability,
        "to": to_actionability,
        "remove_from": remove_from,
        "blocker": blocker,
        "reason": reason,
        "fingerprint": _rebucket_fingerprint_from_request(request),
    }
    return to_actionability


def _allocator_triage_details(
    payload: Any,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if not isinstance(payload, Mapping):
        return details
    for field_name in ALLOCATOR_PCDUMP_TRIAGE_DETAIL_FIELDS:
        if field_name in payload:
            details[field_name] = payload[field_name]
    unit = payload.get("unit")
    if isinstance(unit, str) and unit:
        details["pcdump"] = str(pcdump_cache.cache_path(repo_root, unit))
    return details


def _compact_allocator_triage_payload(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    return dict(payload)


def _allocator_actionability_reason(
    actionability: Mapping[str, Any],
    fallback: str,
) -> str:
    parts = []
    for field_name in ("summary", "next_step"):
        value = actionability.get(field_name)
        if isinstance(value, str) and value:
            parts.append(value)
    return "; ".join(parts) if parts else fallback


def _has_force_vector_conflicts(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


def _has_runnable_recommended_force_vector(payload: Mapping[str, Any]) -> bool:
    force_vector = payload.get("force_vector")
    return (
        isinstance(force_vector, str)
        and bool(force_vector.strip())
        and payload.get("force_vector_runnable") is True
        and payload.get("force_vector_recommended") is True
        and not _has_force_vector_conflicts(payload.get("force_vector_conflicts"))
    )


def _allocator_payload_has_targets(
    payload: Mapping[str, Any],
    actionability: Mapping[str, Any],
) -> bool:
    targets = payload.get("targets")
    if isinstance(targets, list):
        return bool(targets)
    for field_name in (
        "target_count",
        "runnable_target_count",
        "needs_move_count",
        "already_target_count",
        "unknown_current_count",
    ):
        value = actionability.get(field_name)
        if isinstance(value, int) and value > 0:
            return True
    results = payload.get("results")
    if isinstance(results, list):
        return any(
            isinstance(row, Mapping) and row.get("status") == "ok"
            for row in results
        )
    return False


def _force_vector_probe_matches(probe: Any) -> bool:
    return isinstance(probe, Mapping) and probe.get("match") is True


def _force_vector_probe_failed(probe: Any) -> bool:
    if not isinstance(probe, Mapping):
        return False
    if str(probe.get("status") or "") == "failed":
        return True
    returncode = probe.get("returncode")
    if returncode in (None, 0, "0"):
        return False
    try:
        return int(returncode) != 0
    except (TypeError, ValueError):
        return True


def _compact_force_vector_probe(probe: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for field_name in ("label", "ordinal", "status", "entries"):
        if field_name in probe:
            compact[field_name] = probe[field_name]
    return compact


def _force_vector_verify_probes(
    verify: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    probes: list[Mapping[str, Any]] = []
    union = verify.get("union")
    if isinstance(union, Mapping):
        probes.append(union)
    raw_probes = verify.get("probes")
    if isinstance(raw_probes, list):
        probes.extend(probe for probe in raw_probes if isinstance(probe, Mapping))
    return probes


def _allocator_force_vector_verify_result(
    request: HarvestRequest,
    *,
    command: list[str],
    payload: Mapping[str, Any],
    details: dict[str, Any],
) -> HarvestResult | None:
    verify = payload.get("force_vector_verify")
    if not isinstance(verify, Mapping) or verify.get("ran") is not True:
        return None

    probes = _force_vector_verify_probes(verify)
    matched_probes = [
        _compact_force_vector_probe(probe)
        for probe in probes
        if _force_vector_probe_matches(probe)
    ]
    details["force_vector_matched_probes"] = matched_probes
    if matched_probes:
        matched_labels = [
            str(probe.get("label") or "probe")
            for probe in matched_probes
        ]
        details["source_transform_hint"] = {
            "kind": BLOCKER_ALLOCATOR_FORCE_VECTOR_MATCH,
            "matched_probe_labels": matched_labels,
            "force_vector": payload.get("force_vector"),
            "unit": payload.get("unit"),
            "targets": payload.get("targets", []),
        }
        labels = ", ".join(matched_labels)
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="diagnostic_match",
            blocker=BLOCKER_ALLOCATOR_FORCE_VECTOR_MATCH,
            reason=(
                f"force-vector {labels} matched; translate diagnostic "
                "allocator proof into source-shape work"
            ),
            command=command,
            details=details,
        )

    if any(_force_vector_probe_failed(probe) for probe in probes):
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_FORCE_VECTOR_VERIFY_FAILED,
            reason="force-vector verification ran but one or more probes failed",
            command=command,
            details=details,
        )

    source_actionability = _allocator_force_vector_no_match_rebucket(
        request,
        payload=payload,
        details=details,
    )
    return _base_result(
        request,
        harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
        status="no_match",
        blocker=BLOCKER_ALLOCATOR_FORCE_VECTOR_NO_MATCH,
        reason="no force-vector probe matched the target function",
        command=command,
        details=details,
        source_actionability=source_actionability,
    )


def _allocator_pcdump_triage_result(
    request: HarvestRequest,
    *,
    command: list[str],
    payload: Any,
    repo_root: Path,
) -> HarvestResult:
    details = _allocator_triage_details(payload, repo_root=repo_root)
    unclassified_reason = "target vector actionability was missing or malformed"
    if not isinstance(payload, Mapping):
        details["payload"] = _compact_allocator_triage_payload(payload)
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_TRIAGE_UNCLASSIFIED,
            reason=unclassified_reason,
            command=command,
            details=details,
        )

    actionability = payload.get("target_vector_actionability")
    if not isinstance(actionability, Mapping):
        details["payload"] = _compact_allocator_triage_payload(payload)
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_TRIAGE_UNCLASSIFIED,
            reason=unclassified_reason,
            command=command,
            details=details,
        )

    status_value = actionability.get("status")
    if not isinstance(status_value, str) or not status_value:
        details["payload"] = _compact_allocator_triage_payload(payload)
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_TRIAGE_UNCLASSIFIED,
            reason=unclassified_reason,
            command=command,
            details=details,
        )

    reason = _allocator_actionability_reason(actionability, status_value)
    force_vector_result = _allocator_force_vector_verify_result(
        request,
        command=command,
        payload=payload,
        details=details,
    )
    if force_vector_result is not None:
        return force_vector_result

    if status_value == "already-satisfied":
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_SOURCE_LIFETIME,
            reason=reason,
            command=command,
            details=details,
        )
    if status_value == "current-unknown":
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_CURRENT_UNKNOWN,
            reason=reason,
            command=command,
            details=details,
        )

    if not _allocator_payload_has_targets(payload, actionability):
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_NO_TARGETS,
            reason="match-iter-first returned no allocator targets",
            command=command,
            details=details,
        )

    if (
        payload.get("force_vector_runnable") is False
        or payload.get("force_vector_recommended") is False
        or _has_force_vector_conflicts(payload.get("force_vector_conflicts"))
    ):
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_VECTOR_NOT_RUNNABLE,
            reason=reason,
            command=command,
            details=details,
        )

    if status_value == "no-runnable-targets":
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_VECTOR_NOT_RUNNABLE,
            reason=reason,
            command=command,
            details=details,
        )

    if status_value == "needs-move":
        if not _has_runnable_recommended_force_vector(payload):
            return _base_result(
                request,
                harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
                status="blocked",
                blocker=BLOCKER_ALLOCATOR_VECTOR_NOT_RUNNABLE,
                reason=reason,
                command=command,
                details=details,
            )
        return _base_result(
            request,
            harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
            status="blocked",
            blocker=BLOCKER_ALLOCATOR_TARGET_VECTOR,
            reason=reason,
            command=command,
            details=details,
        )

    details["payload"] = _compact_allocator_triage_payload(payload)
    return _base_result(
        request,
        harness=HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
        status="blocked",
        blocker=BLOCKER_ALLOCATOR_TRIAGE_UNCLASSIFIED,
        reason=f"unclassified allocator actionability status: {status_value}",
        command=command,
        details=details,
    )


def _already_matched_result(
    request: HarvestRequest,
    *,
    repo_root: Path,
    harness: str | None,
    match_checker: MatchCheckerRunner,
) -> HarvestResult | None:
    try:
        process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except Exception:
        return None
    if not _match_checker_indicates_match(process):
        return None
    return _base_result(
        request,
        harness=harness,
        status="already-matched",
        blocker=None,
        reason="function already matches; stale queue row skipped",
        command=process.command,
        details={
            "stdout": _short_output(process.stdout),
            "stderr": _short_output(process.stderr),
        },
    )


def _matched_functions_in_source_file(
    repo_root: Path,
    source_file: Path,
    *,
    exclude: str,
) -> list[str]:
    report_path = repo_root / "build" / "GALE01" / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    source_resolved = source_file.resolve()
    matched: list[str] = []
    for unit in report.get("units") or []:
        if not isinstance(unit, dict):
            continue
        metadata = unit.get("metadata") or {}
        unit_source = metadata.get("source_path") or unit.get("name")
        if not isinstance(unit_source, str) or not unit_source:
            continue
        unit_source_path = Path(unit_source)
        if not unit_source_path.is_absolute():
            unit_source_path = repo_root / unit_source_path
        try:
            if unit_source_path.resolve() != source_resolved:
                continue
        except OSError:
            continue
        for function in unit.get("functions") or []:
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or name == exclude:
                continue
            score = _float_or_none(function.get("fuzzy_match_percent"))
            if score is not None and score >= VALIDATED_MATCH_PERCENT:
                matched.append(name)
    return matched


def _same_file_regression_error(
    request: HarvestRequest,
    *,
    repo_root: Path,
    validator: ValidatorRunner,
) -> dict[str, Any] | None:
    if request.source_file is None:
        return None
    for matched_function in _matched_functions_in_source_file(
        repo_root,
        request.source_file,
        exclude=request.function,
    ):
        try:
            regression = validator(
                matched_function,
                cwd=repo_root,
                timeout=request.timeout,
            )
        except BaseException as exc:
            return {
                "regression_function": matched_function,
                "error": str(exc),
            }
        if regression.returncode == 0:
            continue
        return {
            "regression_function": matched_function,
            "validator_command": regression.command,
            "validator_stdout": _short_output(regression.stdout),
            "validator_stderr": _short_output(regression.stderr),
        }
    return None


def _candidate_path_for_apply(candidate_path: str, repo_root: Path) -> Path:
    path = Path(candidate_path)
    if path.is_absolute():
        return path
    for base in (repo_root, repo_root / "tools" / "melee-agent"):
        candidate = base / path
        if candidate.exists():
            return candidate
    return repo_root / path


def _atomic_write_text(path: Path, text: str) -> None:
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(text)
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def _snapshot_source_files(requests: list[HarvestRequest]) -> dict[Path, str]:
    snapshots: dict[Path, str] = {}
    for request in requests:
        if request.source_file is None:
            continue
        path = request.source_file
        if path in snapshots:
            continue
        try:
            snapshots[path] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return snapshots


def _restore_source_files(snapshots: Mapping[Path, str]) -> list[str]:
    errors: list[str] = []
    for path, text in snapshots.items():
        try:
            _atomic_write_text(path, text)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return errors


@dataclass(frozen=True)
class _HeaderApplyCandidate:
    candidate_path: str
    target_path: Path
    candidate_text: str
    target_text: str


def _read_optional_header_apply_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate: Mapping[str, Any] | None,
    harness: str,
    command: list[str],
    candidate_path: str,
    final_match_percent: float,
) -> tuple[_HeaderApplyCandidate | None, HarvestResult | None]:
    header_candidate_path = _candidate_header_path(candidate)
    if header_candidate_path is None:
        return None, None

    candidate_file = _candidate_path_for_apply(header_candidate_path, repo_root)
    if candidate_file.suffix != ".h":
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="retained header candidate is not a .h file",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"header_candidate_path": header_candidate_path},
        )

    target_header = _candidate_header_target(candidate, request, repo_root)
    if target_header is None or not target_header.exists():
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="target header for retained source candidate was not found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"header_candidate_path": str(candidate_file)},
        )

    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = target_header.read_text(encoding="utf-8")
    except OSError as exc:
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target header could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "header_candidate_path": str(candidate_file),
                "header_target": str(target_header),
                "error": str(exc),
            },
        )

    return (
        _HeaderApplyCandidate(
            candidate_path=str(candidate_file),
            target_path=target_header,
            candidate_text=candidate_text,
            target_text=target_text,
        ),
        None,
    )


def _restore_apply_targets(
    source_file: Path,
    source_text: str,
    header_candidate: _HeaderApplyCandidate | None = None,
) -> str | None:
    errors: list[str] = []
    try:
        _atomic_write_text(source_file, source_text)
    except Exception as exc:
        errors.append(str(exc))
    if header_candidate is not None:
        try:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.target_text,
            )
        except Exception as exc:
            errors.append(str(exc))
    return "; ".join(errors) if errors else None


def _apply_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    validator: ValidatorRunner,
    harness: str,
    command: list[str],
    final_match_percent: float,
) -> HarvestResult:
    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    candidate_file = _candidate_path_for_apply(candidate_path, repo_root)
    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = request.source_file.read_text(encoding="utf-8")
    except OSError as exc:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target source could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    candidate_function = extract_function(candidate_text, request.function)
    if candidate_function is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate source did not contain the requested function",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    patched = replace_function(target_text, request.function, candidate_function)
    if patched is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="target source did not contain the requested function",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    try:
        _atomic_write_text(request.source_file, patched)
        validation = validator(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except BaseException as exc:
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "error": str(exc),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed to run",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    if validation.returncode != 0:
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "validator_command": validation.command,
                    "validator_stdout": _short_output(validation.stdout),
                    "validator_stderr": _short_output(validation.stderr),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "validator_command": validation.command,
                "validator_stdout": _short_output(validation.stdout),
                "validator_stderr": _short_output(validation.stderr),
            },
        )

    for matched_function in _matched_functions_in_source_file(
        repo_root,
        request.source_file,
        exclude=request.function,
    ):
        try:
            regression = validator(
                matched_function,
                cwd=repo_root,
                timeout=request.timeout,
            )
        except BaseException as exc:
            try:
                _atomic_write_text(request.source_file, target_text)
            except Exception as rollback_exc:
                return _base_result(
                    request,
                    harness=harness,
                    status="blocked",
                    blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                    reason="post-apply regression guard failed and rollback failed",
                    command=command,
                    candidate_path=candidate_path,
                    final_match_percent=final_match_percent,
                    details={
                        "regression_function": matched_function,
                        "error": str(exc),
                        "rollback_error": str(rollback_exc),
                    },
                )
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "regression_function": matched_function,
                    "error": str(exc),
                },
            )
        if regression.returncode == 0:
            continue
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "regression_function": matched_function,
                    "validator_command": regression.command,
                    "validator_stdout": _short_output(regression.stdout),
                    "validator_stderr": _short_output(regression.stderr),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply regression guard failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "regression_function": matched_function,
                "validator_command": regression.command,
                "validator_stdout": _short_output(regression.stdout),
                "validator_stderr": _short_output(regression.stderr),
            },
        )

    return _base_result(
        request,
        harness=harness,
        status="applied",
        blocker=None,
        reason="validated candidate applied",
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
        applied=True,
        details={"validator_command": validation.command},
    )


def _apply_whole_file_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    candidate: Mapping[str, Any] | None = None,
    validator: ValidatorRunner,
    harness: str,
    command: list[str],
    final_match_percent: float,
) -> HarvestResult:
    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    candidate_file = _candidate_path_for_apply(candidate_path, repo_root)
    if not _is_c_source_path(str(candidate_file)):
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="retained source candidate is not a .c file",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = request.source_file.read_text(encoding="utf-8")
    except OSError as exc:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target source could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    header_candidate, header_error = _read_optional_header_apply_candidate(
        request,
        repo_root=repo_root,
        candidate=candidate,
        harness=harness,
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
    )
    if header_error is not None:
        return header_error

    try:
        if header_candidate is not None:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.candidate_text,
            )
        _atomic_write_text(request.source_file, candidate_text)
        validation = validator(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except BaseException as exc:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "error": str(exc),
                    "rollback_error": rollback_error,
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed to run",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    if validation.returncode != 0:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "validator_command": validation.command,
                    "validator_stdout": _short_output(validation.stdout),
                    "validator_stderr": _short_output(validation.stderr),
                    "rollback_error": rollback_error,
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "validator_command": validation.command,
                "validator_stdout": _short_output(validation.stdout),
                "validator_stderr": _short_output(validation.stderr),
            },
        )

    regression_error = _same_file_regression_error(
        request,
        repo_root=repo_root,
        validator=validator,
    )
    if regression_error is not None:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={**regression_error, "rollback_error": rollback_error},
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply regression guard failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details=regression_error,
        )

    return _base_result(
        request,
        harness=harness,
        status="applied",
        blocker=None,
        reason="validated candidate applied",
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
        applied=True,
        details={
            "validator_command": validation.command,
            **(
                {
                    "header_candidate_path": header_candidate.candidate_path,
                    "header_target": str(header_candidate.target_path),
                }
                if header_candidate is not None
                else {}
            ),
        },
    )


def _adapter_command(request: HarvestRequest, harness: str) -> list[str]:
    if harness == HARNESS_FRAME_TRANSFORM:
        return _frame_transform_command(request)
    if harness == HARNESS_COALESCE:
        return _coalesce_command(request)
    if harness == HARNESS_SELECT_ORDER:
        return _select_order_command(request)
    if harness == HARNESS_INDEXED_STRUCT:
        return _indexed_struct_command(request)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return _name_magic_source_command(request)
    if harness == HARNESS_CONTROL_FLOW_SHAPE:
        return _control_flow_shape_command(request)
    if harness == HARNESS_LIFETIME_LAYOUT:
        return _lifetime_layout_command(request)
    if harness == HARNESS_ALLOCATOR_PCDUMP_TRIAGE:
        return _allocator_pcdump_triage_command(request)
    raise ValueError(f"unsupported harness: {harness}")


def _normalize_layer_sequence(request: HarvestRequest) -> list[dict[str, Any]]:
    explicit = request.facts.get("harnesses")
    if isinstance(explicit, list):
        layers: list[dict[str, Any]] = []
        for item in explicit:
            if isinstance(item, str):
                harness = item.strip().lower()
                if harness:
                    layers.append({"harness": harness})
            elif isinstance(item, Mapping):
                layer = dict(item)
                harness = layer.get("harness")
                if harness:
                    layer["harness"] = str(harness).strip().lower()
                    layers.append(layer)
        return layers

    selected: list[str] = []
    if (
        not _is_blocked_data_symbol_request(request)
        and (
            request.work_bucket == "data-symbol-relocation"
            or request.primary in {"data-symbol-or-relocation", "data-symbol-relocation"}
            or request.source_actionability == "current-tools-data-symbol"
            or request.headline_tool == "checkdiff-name-magic"
        )
    ):
        selected.append(HARNESS_NAME_MAGIC_SOURCE)
    if (
        request.primary == "indexed-struct-pointer-materialization"
        or request.source_actionability == "current-tools-indexed-pointer"
    ):
        selected.append(HARNESS_INDEXED_STRUCT)
    row_harness = select_harness(request)
    if row_harness is not None:
        selected.append(row_harness)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for harness in selected:
        if harness in seen:
            continue
        seen.add(harness)
        deduped.append({"harness": harness})
    return deduped


def _layer_request(request: HarvestRequest, layer_facts: Mapping[str, Any]) -> HarvestRequest:
    facts = dict(request.facts)
    facts.pop("harnesses", None)
    facts.update(dict(layer_facts))
    return replace(request, facts=facts)


def _execute_harness_payload(
    request: HarvestRequest,
    *,
    harness: str,
    repo_root: Path,
    runner: HarnessRunner,
) -> tuple[list[str], Any | None, HarvestResult | None]:
    if harness not in REGISTERED_HARNESSES:
        return [], None, _base_result(
            request,
            harness=harness,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no registered harness matched the layer",
        )
    if request.source_file is None:
        return [], None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
        )
    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER} and not request.facts.get(
        "target"
    ):
        return [], None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_REGISTER_TARGET,
            reason="register harness requires facts.target",
        )

    command = _adapter_command(request, harness)
    try:
        process = runner(
            command,
            cwd=repo_root / "tools" / "melee-agent",
            timeout=request.timeout,
        )
    except Exception as exc:
        return command, None, _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess failed to run",
            command=command,
            details={"error": str(exc)},
        )
    if process.returncode != 0:
        return command, None, _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess exited nonzero",
            command=command,
            details={
                "returncode": process.returncode,
                "stdout": _short_output(process.stdout),
                "stderr": _short_output(process.stderr),
            },
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return command, None, _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_INVALID_JSON,
            reason="harness did not emit valid JSON",
            command=command,
            details={"error": str(exc), "stdout": _short_output(process.stdout)},
        )
    return command, payload, None


def _rank_sub100_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates = []
    for candidate in _iter_candidates(payload):
        if candidate.get("status") != "ok":
            continue
        if _candidate_source_path(candidate) is None:
            continue
        score = extract_candidate_score(candidate)
        if score is None:
            continue
        if abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON:
            continue
        candidates.append(candidate)
    candidates.sort(
        key=lambda candidate: (
            extract_candidate_score(candidate)
            if extract_candidate_score(candidate) is not None
            else -1.0
        ),
        reverse=True,
    )
    return candidates


def _apply_partial_layer_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    candidate: Mapping[str, Any] | None = None,
    match_checker: MatchCheckerRunner,
    validator: ValidatorRunner,
    harness: str,
    command: list[str],
    final_match_percent: float,
    before_payload: Mapping[str, Any] | None,
    preserve: bool,
) -> HarvestResult:
    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    candidate_file = _candidate_path_for_apply(candidate_path, repo_root)
    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = request.source_file.read_text(encoding="utf-8")
    except OSError as exc:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target source could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    header_candidate, header_error = _read_optional_header_apply_candidate(
        request,
        repo_root=repo_root,
        candidate=candidate,
        harness=harness,
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
    )
    if header_error is not None:
        return header_error

    if harness == HARNESS_NAME_MAGIC_SOURCE:
        patched = candidate_text
    else:
        candidate_function = extract_function(candidate_text, request.function)
        if candidate_function is None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_TRANSFER_FAILED,
                reason="candidate source did not contain the requested function",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
            )
        patched = replace_function(target_text, request.function, candidate_function)
        if patched is None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_TRANSFER_FAILED,
                reason="target source did not contain the requested function",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
            )

    try:
        if header_candidate is not None:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.candidate_text,
            )
        _atomic_write_text(request.source_file, patched)
        after_process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
        after_payload = _strict_match_payload(after_process)
        verified = _payload_verifies_layer_improvement(
            before_payload,
            after_payload,
            harness=harness,
        )
        regression_error = (
            _same_file_regression_error(
                request,
                repo_root=repo_root,
                validator=validator,
            )
            if verified
            else None
        )
    except BaseException as exc:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="partial layer validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "error": str(exc),
                    "rollback_error": rollback_error,
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="partial layer validation failed to run",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    details = {
        "layer_outcome": "verified-improvement" if verified else "not-improved",
        "before_match_percent": _payload_match_percent(before_payload),
        "after_match_percent": _payload_match_percent(after_payload),
        "before_classification": _payload_classification_primary(before_payload),
        "after_classification": _payload_classification_primary(after_payload),
        "after_match_checker_command": after_process.command,
        "after_match_checker_stdout": _short_output(after_process.stdout),
        "after_match_checker_stderr": _short_output(after_process.stderr),
    }
    if header_candidate is not None:
        details["header_candidate_path"] = header_candidate.candidate_path
        details["header_target"] = str(header_candidate.target_path)
    if regression_error is not None:
        details.update(regression_error)

    if verified and regression_error is None and preserve:
        return _base_result(
            request,
            harness=harness,
            status="applied",
            blocker=None,
            reason="verified layer improvement applied",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            applied=True,
            details=details,
        )

    rollback_error = _restore_apply_targets(
        request.source_file,
        target_text,
        header_candidate,
    )
    if rollback_error is not None:
        details["rollback_error"] = rollback_error
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="partial layer validation failed and rollback failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details=details,
        )

    if verified and regression_error is None:
        return _base_result(
            request,
            harness=harness,
            status="improved",
            blocker=None,
            reason="verified layer improvement found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            applied=False,
            details=details,
        )

    return _base_result(
        request,
        harness=harness,
        status="blocked",
        blocker=BLOCKER_APPLY_VALIDATION_FAILED,
        reason=(
            "post-apply regression guard failed"
            if regression_error is not None
            else "candidate did not verify a strict post-apply improvement"
        ),
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
        details=details,
    )


def _compose_result(
    request: HarvestRequest,
    *,
    status: str,
    blocker: str | None,
    reason: str,
    layers: list[HarvestResult],
    harness_sequence: list[str],
    stop_reason: str,
    not_observed_layers: list[str] | None = None,
    final_layer: HarvestResult | None = None,
    applied: bool | None = None,
) -> HarvestResult:
    final_layer = final_layer or (layers[-1] if layers else None)
    details = {
        "layers": [layer.to_dict() for layer in layers],
        "stop_reason": stop_reason,
        "harness_sequence": harness_sequence,
        "not_observed_layers": not_observed_layers or [],
    }
    source_actionability = None
    if final_layer is not None:
        if final_layer.source_actionability != request.source_actionability:
            source_actionability = final_layer.source_actionability
        for key in ("source_actionability_rebucket", "malformed_source_candidate"):
            if key in final_layer.details:
                details[key] = final_layer.details[key]
    return _base_result(
        request,
        harness="composed",
        status=status,
        blocker=blocker,
        reason=reason,
        command=final_layer.command if final_layer is not None else [],
        candidate_path=final_layer.candidate_path if final_layer is not None else None,
        final_match_percent=(
            final_layer.final_match_percent if final_layer is not None else None
        ),
        applied=(
            any(layer.applied for layer in layers)
            if applied is None
            else applied
        ),
        details=details,
        source_actionability=source_actionability,
    )


def run_composed_harvest_request(
    request: HarvestRequest,
    *,
    repo_root: Path,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> HarvestResult:
    layer_facts = _normalize_layer_sequence(request)
    harness_sequence = [str(layer.get("harness") or "") for layer in layer_facts]
    if not layer_facts:
        return _compose_result(
            request,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no harness sequence was available for composition",
            layers=[],
            harness_sequence=[],
            stop_reason="empty-harness-sequence",
        )

    layers: list[HarvestResult] = []
    for index, facts in enumerate(layer_facts):
        harness = str(facts.get("harness") or "").strip().lower()
        layer_request = _layer_request(request, facts)
        layer_validator = validator
        layer_match_checker = match_checker
        if harness == HARNESS_NAME_MAGIC_SOURCE:
            if validator is _default_validator:
                layer_validator = _default_no_name_magic_validator
            if match_checker is _default_match_checker:
                layer_match_checker = _default_no_name_magic_match_checker

        before_payload: dict[str, Any] | None = None
        try:
            before_process = layer_match_checker(
                request.function,
                cwd=repo_root,
                timeout=request.timeout,
            )
            before_payload = _strict_match_payload(before_process)
        except Exception:
            before_process = None
        if _strict_payload_indicates_match(before_payload):
            if layers:
                return _compose_result(
                    request,
                    status="already-matched",
                    blocker=None,
                    reason="function reached match=true after composed layers",
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason="matched-after-layers",
                    final_layer=layers[-1],
                )
            return _compose_result(
                request,
                status="already-matched",
                blocker=None,
                reason="function already matches; stale queue row skipped",
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason="already-matched-before-layer",
                final_layer=layers[-1] if layers else None,
            )

        command, payload, error_result = _execute_harness_payload(
            layer_request,
            harness=harness,
            repo_root=repo_root,
            runner=runner,
        )
        if error_result is not None:
            layers.append(error_result)
            return _compose_result(
                request,
                status=error_result.status,
                blocker=error_result.blocker,
                reason=error_result.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason=f"layer-{error_result.status}",
                final_layer=error_result,
            )

        assert payload is not None
        if harness == HARNESS_ALLOCATOR_PCDUMP_TRIAGE:
            layer = _allocator_pcdump_triage_result(
                layer_request,
                command=command,
                payload=payload,
                repo_root=repo_root,
            )
            layers.append(layer)
            return _compose_result(
                request,
                status=layer.status,
                blocker=layer.blocker,
                reason=layer.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason=f"layer-{layer.status}",
                final_layer=layer,
            )

        if harness == HARNESS_NAME_MAGIC_SOURCE:
            candidate, unsupported_candidate_path = best_validated_name_magic_candidate(
                payload
            )
        else:
            candidate = best_validated_candidate(payload)
            unsupported_candidate_path = None

        if candidate is not None:
            final_match_percent = extract_candidate_score(candidate)
            candidate_path = _candidate_source_path(candidate)
            assert final_match_percent is not None
            assert candidate_path is not None
            if not request.apply:
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status="validated",
                    blocker=None,
                    reason="validated candidate found",
                    command=command,
                    candidate_path=candidate_path,
                    final_match_percent=final_match_percent,
                )
                layers.append(layer)
                return _compose_result(
                    request,
                    status="validated",
                    blocker=None,
                    reason="validated candidate found",
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason="dry-run-first-candidate-layer",
                    not_observed_layers=harness_sequence[index + 1 :],
                    final_layer=layer,
                    applied=False,
                )
            if harness == HARNESS_NAME_MAGIC_SOURCE:
                layer = _apply_whole_file_candidate(
                    layer_request,
                    repo_root=repo_root,
                    candidate_path=candidate_path,
                    candidate=candidate,
                    validator=layer_validator,
                    harness=harness,
                    command=command,
                    final_match_percent=final_match_percent,
                )
            else:
                layer = _apply_candidate(
                    layer_request,
                    repo_root=repo_root,
                    candidate_path=candidate_path,
                    validator=layer_validator,
                    harness=harness,
                    command=command,
                    final_match_percent=final_match_percent,
                )
            layers.append(layer)
            if layer.status not in {"applied", "validated"}:
                return _compose_result(
                    request,
                    status=layer.status,
                    blocker=layer.blocker,
                    reason=layer.reason,
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason=f"layer-{layer.status}",
                    final_layer=layer,
                )
            continue

        if unsupported_candidate_path is not None:
            layer = _base_result(
                layer_request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
                reason="retained source candidate is not a .c file",
                command=command,
                candidate_path=unsupported_candidate_path,
                details=no_validated_candidate_details(payload),
            )
            layers.append(layer)
            return _compose_result(
                request,
                status=layer.status,
                blocker=layer.blocker,
                reason=layer.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason="layer-blocked",
                final_layer=layer,
            )

        sub100_candidates = _rank_sub100_candidates(payload)
        last_failed_layer: HarvestResult | None = None
        for sub_candidate in sub100_candidates:
            final_match_percent = extract_candidate_score(sub_candidate)
            candidate_path = _candidate_source_path(sub_candidate)
            assert final_match_percent is not None
            assert candidate_path is not None
            layer = _apply_partial_layer_candidate(
                layer_request,
                repo_root=repo_root,
                candidate_path=candidate_path,
                candidate=sub_candidate,
                match_checker=layer_match_checker,
                validator=layer_validator,
                harness=harness,
                command=command,
                final_match_percent=final_match_percent,
                before_payload=before_payload,
                preserve=request.apply,
            )
            if layer.status in {"applied", "improved"}:
                layers.append(layer)
                if not request.apply:
                    return _compose_result(
                        request,
                        status="improved",
                        blocker=None,
                        reason="verified layer improvement found",
                        layers=layers,
                        harness_sequence=harness_sequence,
                        stop_reason="dry-run-first-candidate-layer",
                        not_observed_layers=harness_sequence[index + 1 :],
                        final_layer=layer,
                        applied=False,
                    )
                break
            last_failed_layer = layer
        else:
            harness_blocker = _harness_blocker_result(payload)
            if harness_blocker is not None:
                status, blocker, reason = harness_blocker
                details = no_validated_candidate_details(payload)
                source_actionability = _malformed_source_rebucket(
                    layer_request,
                    harness=harness,
                    blocker=blocker,
                    details=details,
                )
                if source_actionability is None:
                    source_actionability = _no_name_magic_candidate_rebucket(
                        layer_request,
                        harness=harness,
                        blocker=blocker,
                        details=details,
                        payload=payload,
                    )
                if source_actionability is None:
                    source_actionability = _frame_transform_no_validated_rebucket(
                        layer_request,
                        harness=harness,
                        blocker=blocker,
                        details=details,
                    )
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status=status,
                    blocker=blocker,
                    reason=reason,
                    command=command,
                    details=details,
                    source_actionability=source_actionability,
                )
            elif last_failed_layer is not None:
                layer = last_failed_layer
            else:
                details = no_validated_candidate_details(payload)
                source_actionability = _frame_transform_no_validated_rebucket(
                    layer_request,
                    harness=harness,
                    blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
                    details=details,
                )
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status="no_match",
                    blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
                    reason="no validated 100% candidate was found",
                    command=command,
                    details=details,
                    source_actionability=source_actionability,
                )
            layers.append(layer)
            return _compose_result(
                request,
                status=layer.status,
                blocker=layer.blocker,
                reason=layer.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason=f"layer-{layer.status}",
                final_layer=layer,
            )

    try:
        final_process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
        final_payload = _strict_match_payload(final_process)
    except Exception:
        final_payload = None
    if _strict_payload_indicates_match(final_payload):
        return _compose_result(
            request,
            status="already-matched",
            blocker=None,
            reason="function reached match=true after composed layers",
            layers=layers,
            harness_sequence=harness_sequence,
            stop_reason="matched-after-layers",
            final_layer=layers[-1] if layers else None,
        )

    final_layer = layers[-1]
    return _compose_result(
        request,
        status=final_layer.status,
        blocker=final_layer.blocker,
        reason=final_layer.reason,
        layers=layers,
        harness_sequence=harness_sequence,
        stop_reason="layer-sequence-exhausted",
        final_layer=final_layer,
    )


def run_harvest_request(
    request: HarvestRequest,
    *,
    repo_root: Path,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> HarvestResult:
    harness = select_harness(request)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        if validator is _default_validator:
            validator = _default_no_name_magic_validator
        if match_checker is _default_match_checker:
            match_checker = _default_no_name_magic_match_checker

    if request.apply:
        already_matched = _already_matched_result(
            request,
            repo_root=repo_root,
            harness=harness,
            match_checker=match_checker,
        )
        if already_matched is not None:
            return already_matched

    if harness is None:
        return _base_result(
            request,
            harness=None,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no registered harness matched the row",
        )

    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
        )

    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER} and not request.facts.get(
        "target"
    ):
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_REGISTER_TARGET,
            reason="register harness requires facts.target",
        )

    command = _adapter_command(request, harness)
    try:
        process = runner(
            command,
            cwd=repo_root / "tools" / "melee-agent",
            timeout=request.timeout,
        )
    except Exception as exc:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess failed to run",
            command=command,
            details={"error": str(exc)},
        )

    if process.returncode != 0:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess exited nonzero",
            command=command,
            details={
                "returncode": process.returncode,
                "stdout": _short_output(process.stdout),
                "stderr": _short_output(process.stderr),
            },
        )

    try:
        harness_json = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_INVALID_JSON,
            reason="harness did not emit valid JSON",
            command=command,
            details={"error": str(exc), "stdout": _short_output(process.stdout)},
        )

    if harness == HARNESS_ALLOCATOR_PCDUMP_TRIAGE:
        return _allocator_pcdump_triage_result(
            request,
            command=command,
            payload=harness_json,
            repo_root=repo_root,
        )

    unsupported_candidate_path = None
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        candidate, unsupported_candidate_path = best_validated_name_magic_candidate(
            harness_json
        )
    else:
        candidate = best_validated_candidate(harness_json)
    if candidate is None:
        if unsupported_candidate_path is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
                reason="retained source candidate is not a .c file",
                command=command,
                candidate_path=unsupported_candidate_path,
                details=no_validated_candidate_details(harness_json),
            )
        harness_blocker = _harness_blocker_result(harness_json)
        if harness_blocker is not None:
            status, blocker, reason = harness_blocker
            details = no_validated_candidate_details(harness_json)
            source_actionability = _malformed_source_rebucket(
                request,
                harness=harness,
                blocker=blocker,
                details=details,
            )
            if source_actionability is None:
                source_actionability = _no_name_magic_candidate_rebucket(
                    request,
                    harness=harness,
                    blocker=blocker,
                    details=details,
                    payload=harness_json,
                )
            if source_actionability is None:
                source_actionability = _frame_transform_no_validated_rebucket(
                    request,
                    harness=harness,
                    blocker=blocker,
                    details=details,
                )
            return _base_result(
                request,
                harness=harness,
                status=status,
                blocker=blocker,
                reason=reason,
                command=command,
                details=details,
                source_actionability=source_actionability,
            )
        details = no_validated_candidate_details(harness_json)
        source_actionability = _frame_transform_no_validated_rebucket(
            request,
            harness=harness,
            blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
            details=details,
        )
        return _base_result(
            request,
            harness=harness,
            status="no_match",
            blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
            reason="no validated 100% candidate was found",
            command=command,
            details=details,
            source_actionability=source_actionability,
        )

    final_match_percent = extract_candidate_score(candidate)
    candidate_path = _candidate_source_path(candidate)
    assert final_match_percent is not None
    assert candidate_path is not None
    if not request.apply:
        return _base_result(
            request,
            harness=harness,
            status="validated",
            blocker=None,
            reason="validated candidate found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return _apply_whole_file_candidate(
            request,
            repo_root=repo_root,
            candidate_path=candidate_path,
            candidate=candidate,
            validator=validator,
            harness=harness,
            command=command,
            final_match_percent=final_match_percent,
        )

    return _apply_candidate(
        request,
        repo_root=repo_root,
        candidate_path=candidate_path,
        validator=validator,
        harness=harness,
        command=command,
        final_match_percent=final_match_percent,
    )


def summarize_ledger(results: list[HarvestResult | dict[str, Any]]) -> dict[str, Any]:
    normalized = [
        result.to_dict() if isinstance(result, HarvestResult) else result
        for result in results
    ]
    by_status: Counter[str] = Counter()
    by_harness: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    by_blocker: Counter[str] = Counter()

    for result in normalized:
        by_status[str(result.get("status") or "unknown")] += 1
        by_harness[str(result.get("harness") or "unsupported")] += 1
        tier = (
            result.get("frame_closability_tier")
            or result.get("source_actionability")
            or "unclassified"
        )
        by_tier[str(tier)] += 1
        blocker = result.get("blocker")
        if blocker:
            by_blocker[str(blocker)] += 1

    return {
        "total_rows": len(normalized),
        "processed": len(normalized),
        "by_status": dict(by_status),
        "by_harness": dict(by_harness),
        "by_tier": dict(by_tier),
        "by_blocker": dict(by_blocker),
    }


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _sorted_strings(values: set[str]) -> list[str]:
    return sorted(value for value in values if value)


def _read_harvest_ledger(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"harvest ledger must be a JSON object: {path}")
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError(f"harvest ledger missing results array: {path}")
    return data


def _suggest_ledger_impact(
    *,
    applied_count: int,
    retained_source_count: int,
    positive_candidate_count: int,
    negative_evidence_count: int,
) -> str:
    if applied_count > 0:
        return "matched"
    if retained_source_count > 0:
        return "retained-source-improvement"
    if positive_candidate_count > 0:
        return "positive-candidate/no-retained-source"
    if negative_evidence_count > 0:
        return "negative-evidence"
    return "diagnostic-only"


def _result_retained_source_status(
    result: Mapping[str, Any],
    *,
    status: str,
    ledger_apply: Any,
) -> bool:
    if status == "applied":
        return True
    applied_marker = result.get("applied")
    if applied_marker is True:
        return True
    if applied_marker is False or ledger_apply is False:
        return False
    return status in RETAINED_SOURCE_STATUSES


def summarize_harvest_ledgers(
    ledger_paths: list[Path],
    *,
    repeated_blocker_threshold: int = 3,
) -> dict[str, Any]:
    """Summarize harvest ledger JSON without running builds or DB lookups."""
    if not ledger_paths:
        raise ValueError("at least one harvest ledger path is required")

    by_status: Counter[str] = Counter()
    by_harness: Counter[str] = Counter()
    by_work_bucket: Counter[str] = Counter()
    by_blocker: Counter[str] = Counter()
    blocker_functions: dict[str, set[str]] = {}
    blocker_harnesses: dict[str, set[str]] = {}
    blocker_buckets: dict[str, set[str]] = {}
    applied_functions: set[str] = set()
    improved_functions: set[str] = set()
    validated_functions: set[str] = set()
    retained_source_functions: set[str] = set()
    negative_evidence_functions: set[str] = set()
    filter_counts: Counter[str] = Counter()
    filter_buckets: dict[str, set[str]] = {}
    filter_values: dict[str, Any] = {}
    filtered_ledger_count = 0
    raw_ledger_count = 0

    total_rows = 0
    for path in ledger_paths:
        ledger = _read_harvest_ledger(path)
        ledger_bucket = str(ledger.get("work_bucket") or "")
        ledger_apply = ledger.get("apply")
        filters = ledger.get("filters")
        if filters is None:
            raw_ledger_count += 1
        else:
            filtered_ledger_count += 1
            filter_key = json.dumps(filters, sort_keys=True)
            filter_counts[filter_key] += 1
            filter_values[filter_key] = filters
            if ledger_bucket:
                filter_buckets.setdefault(filter_key, set()).add(ledger_bucket)
        for raw_result in ledger["results"]:
            if not isinstance(raw_result, Mapping):
                continue
            total_rows += 1
            function = str(raw_result.get("function") or "")
            status = str(raw_result.get("status") or "unknown")
            harness = str(raw_result.get("harness") or "unsupported")
            work_bucket = str(raw_result.get("work_bucket") or ledger_bucket or "unknown")
            blocker = raw_result.get("blocker")

            by_status[status] += 1
            by_harness[harness] += 1
            by_work_bucket[work_bucket] += 1

            if status == "applied" and function:
                applied_functions.add(function)
            elif status == "improved" and function:
                improved_functions.add(function)
            elif status == "validated" and function:
                validated_functions.add(function)
            if (
                function
                and _result_retained_source_status(
                    raw_result,
                    status=status,
                    ledger_apply=ledger_apply,
                )
            ):
                retained_source_functions.add(function)
            if status in NEGATIVE_EVIDENCE_STATUSES and function:
                negative_evidence_functions.add(function)

            if isinstance(blocker, str) and blocker:
                by_blocker[blocker] += 1
                blocker_functions.setdefault(blocker, set()).add(function)
                blocker_harnesses.setdefault(blocker, set()).add(harness)
                blocker_buckets.setdefault(blocker, set()).add(work_bucket)

    repeated_blockers = []
    threshold = max(repeated_blocker_threshold, 1)
    for blocker, count in sorted(by_blocker.items()):
        if count < threshold:
            continue
        repeated_blockers.append({
            "blocker": blocker,
            "count": count,
            "functions": _sorted_strings(blocker_functions.get(blocker, set())),
            "harnesses": _sorted_strings(blocker_harnesses.get(blocker, set())),
            "work_buckets": _sorted_strings(blocker_buckets.get(blocker, set())),
        })

    filter_summaries = [
        {
            "count": filter_counts[key],
            "filters": filter_values[key],
            "work_buckets": _sorted_strings(filter_buckets.get(key, set())),
        }
        for key in sorted(filter_counts)
    ]

    return {
        "ledger_count": len(ledger_paths),
        "ledgers": [str(path) for path in ledger_paths],
        "total_rows": total_rows,
        "by_status": _sorted_counts(by_status),
        "by_harness": _sorted_counts(by_harness),
        "by_work_bucket": _sorted_counts(by_work_bucket),
        "by_blocker": _sorted_counts(by_blocker),
        "applied_functions": _sorted_strings(applied_functions),
        "improved_functions": _sorted_strings(improved_functions),
        "validated_functions": _sorted_strings(validated_functions),
        "retained_source_functions": _sorted_strings(retained_source_functions),
        "negative_evidence_functions": _sorted_strings(negative_evidence_functions),
        "repeated_blocker_threshold": threshold,
        "repeated_blockers": repeated_blockers,
        "filtered_ledger_count": filtered_ledger_count,
        "raw_ledger_count": raw_ledger_count,
        "filters": filter_summaries,
        "suggested_impact": _suggest_ledger_impact(
            applied_count=len(applied_functions),
            retained_source_count=len(retained_source_functions),
            positive_candidate_count=len(
                (improved_functions | validated_functions) - retained_source_functions
            ),
            negative_evidence_count=len(negative_evidence_functions),
        ),
    }


def _build_ledger(
    *,
    work_bucket: str,
    started_at: str,
    finished_at: str,
    apply: bool,
    min_match: float,
    limit: int | None,
    taxonomy_queue: Path,
    target_map_path: Path | None,
    filters: HarvestFilters | None = None,
    preflight: dict[str, Any] | None = None,
    results: list[HarvestResult | dict[str, Any]],
) -> dict[str, Any]:
    result_dicts = [
        result.to_dict() if isinstance(result, HarvestResult) else result
        for result in results
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "work_bucket": work_bucket,
        "started_at": started_at,
        "finished_at": finished_at,
        "apply": apply,
        "min_match": min_match,
        "limit": limit,
        "taxonomy_queue": str(taxonomy_queue),
        "target_map": str(target_map_path) if target_map_path else None,
        "filters": filters.to_dict() if filters is not None else None,
        "preflight": preflight,
        "summary": summarize_ledger(result_dicts),
        "results": result_dicts,
    }


def write_ledger(
    path: Path,
    *,
    work_bucket: str,
    started_at: str,
    finished_at: str,
    apply: bool,
    min_match: float,
    limit: int | None,
    taxonomy_queue: Path,
    target_map_path: Path | None,
    filters: HarvestFilters | None = None,
    preflight: dict[str, Any] | None = None,
    results: list[HarvestResult | dict[str, Any]],
) -> dict[str, Any]:
    ledger = _build_ledger(
        work_bucket=work_bucket,
        started_at=started_at,
        finished_at=finished_at,
        apply=apply,
        min_match=min_match,
        limit=limit,
        taxonomy_queue=taxonomy_queue,
        target_map_path=target_map_path,
        filters=filters,
        preflight=preflight,
        results=results,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ledger


def run_harvest(
    work_bucket: str,
    *,
    repo_root: Path,
    queue_path: Path | None = None,
    taxonomy_dir: Path | None = None,
    min_match: float = 0.0,
    limit: int | None = None,
    target_map: dict[str, dict[str, Any]] | None = None,
    target_map_path: Path | None = None,
    ledger_path: Path | None = None,
    apply: bool = False,
    compose: bool = False,
    timeout: int = 120,
    max_probes: int = 8,
    filters: HarvestFilters | None = None,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> dict[str, Any]:
    started_at = _utc_now()
    if queue_path is None:
        queue_root = (
            taxonomy_dir
            if taxonomy_dir is not None
            else repo_root / "build" / "function-taxonomy" / "queues"
        )
        queue_path = queue_root / f"{work_bucket}.tsv"

    if target_map is None:
        target_map = load_target_map(target_map_path)

    if filters is not None and filters.is_active():
        preview = preview_harvest_queue(
            queue_path,
            work_bucket=work_bucket,
            repo_root=repo_root,
            min_match=min_match,
            limit=limit,
            target_map=target_map,
            filters=filters,
            sample_limit=0,
        )
        if preview["counts"]["matching_rows"] == 0:
            raise ValueError(
                "filters matched zero rows; run with --preview to inspect "
                "current queue facets"
            )

    requests = load_queue_rows(
        queue_path,
        work_bucket=work_bucket,
        repo_root=repo_root,
        min_match=min_match,
        limit=limit,
        target_map=target_map,
        apply=apply,
        timeout=timeout,
        max_probes=max_probes,
        filters=filters,
    )
    source_snapshots = {} if apply else _snapshot_source_files(requests)
    try:
        pcdump_preflight = _run_pcdump_preflight(
            requests,
            repo_root=repo_root,
            runner=runner,
            timeout=timeout,
            compose=compose,
        )
        preflight = {
            "pcdump": pcdump_preflight.to_dict()
        }
        request_runner = run_composed_harvest_request if compose else run_harvest_request
        results: list[HarvestResult] = []
        for request in requests:
            unsafe_result = _unsafe_local_pcdump_result(
                request,
                repo_root=repo_root,
                preflight_report=pcdump_preflight,
            )
            if unsafe_result is not None:
                results.append(unsafe_result)
                continue
            results.append(
                request_runner(
                    request,
                    repo_root=repo_root,
                    runner=runner,
                    validator=validator,
                    match_checker=match_checker,
                )
            )
        finished_at = _utc_now()
        if ledger_path is not None:
            return write_ledger(
                ledger_path,
                work_bucket=work_bucket,
                started_at=started_at,
                finished_at=finished_at,
                apply=apply,
                min_match=min_match,
                limit=limit,
                taxonomy_queue=queue_path,
                target_map_path=target_map_path,
                filters=filters,
                preflight=preflight,
                results=results,
            )
        return _build_ledger(
            work_bucket=work_bucket,
            started_at=started_at,
            finished_at=finished_at,
            apply=apply,
            min_match=min_match,
            limit=limit,
            taxonomy_queue=queue_path,
            target_map_path=target_map_path,
            filters=filters,
            preflight=preflight,
            results=results,
        )
    finally:
        restore_errors = _restore_source_files(source_snapshots)
        if restore_errors and sys.exc_info()[0] is None:
            raise RuntimeError(
                "dry-run source restore failed: " + "; ".join(restore_errors)
            )
