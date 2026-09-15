from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable, Iterable

from .deinline import build_deinline_patch
from .detect import (
    classify_arg,
    find_call_sites,
    parse_inline_defs,
    resolve_inline_defs,
)
from .score import classify_score, diff_scores
from .store import InlineLeverageStore
from .types import InlineDef, LeverageRecord, ScoreResult

InlineScorer = Callable[[str, str], ScoreResult]


def _record_for(
    *,
    run_id: str,
    function: str,
    unit: str,
    inline_def: InlineDef,
    n_call_sites: int,
    shape_args: list[str],
    verdict: str,
    expansion_form: str | None,
    score: ScoreResult | None,
    error: str | None,
) -> LeverageRecord:
    return LeverageRecord(
        run_id=run_id,
        function=function,
        unit=unit,
        inline_name=inline_def.name,
        def_location=inline_def.def_location,
        def_file=inline_def.def_file,
        is_static=inline_def.is_static,
        n_call_sites=n_call_sites,
        baseline_pct=None if score is None else score.baseline_pct,
        deinlined_pct=None if score is None else score.deinlined_pct,
        delta_fuzzy=None if score is None else score.delta_fuzzy,
        baseline_ndl=None if score is None else score.baseline_ndl,
        deinlined_ndl=None if score is None else score.deinlined_ndl,
        delta_struct=None if score is None else score.delta_struct,
        verdict=verdict,  # type: ignore[arg-type]
        expansion_form=expansion_form,
        shape_return=inline_def.return_class,
        shape_body=inline_def.body_kind,
        shape_args=shape_args,
        n_statements=inline_def.n_statements,
        error=error,
        evidence=None if score is None else score.evidence,
    )


def _shape_args(call_args: Iterable[str]) -> list[str]:
    return [classify_arg(arg) for arg in call_args]


def measure_function_source(
    *,
    source: str,
    function: str,
    unit: str,
    run_id: str,
    scorer: InlineScorer | None,
    inline_defs: dict[str, InlineDef] | None = None,
    epsilon: float = 0.05,
    max_pairs: int | None = None,
) -> list[LeverageRecord]:
    defs = inline_defs or {item.name: item for item in parse_inline_defs(source, unit)}
    records: list[LeverageRecord] = []
    for inline_def in defs.values():
        calls = find_call_sites(source, function, inline_def.name)
        if not calls:
            continue
        all_arg_kinds: list[str] = []
        for call in calls:
            all_arg_kinds.extend(_shape_args(call.args))
        patch = build_deinline_patch(source, function, inline_def, calls)
        if not patch.ok:
            records.append(_record_for(
                run_id=run_id,
                function=function,
                unit=unit,
                inline_def=inline_def,
                n_call_sites=len(calls),
                shape_args=all_arg_kinds,
                verdict="unsupported",
                expansion_form=patch.expansion_form,
                score=None,
                error=patch.unsupported_reason,
            ))
        elif scorer is None:
            records.append(_record_for(
                run_id=run_id,
                function=function,
                unit=unit,
                inline_def=inline_def,
                n_call_sites=len(calls),
                shape_args=all_arg_kinds,
                verdict="unsupported",
                expansion_form=patch.expansion_form,
                score=None,
                error="dry-run: scoring disabled",
            ))
        else:
            try:
                score = scorer(patch.new_source or source, inline_def.name)
                verdict = classify_score(score, epsilon=epsilon)
                records.append(_record_for(
                    run_id=run_id,
                    function=function,
                    unit=unit,
                    inline_def=inline_def,
                    n_call_sites=len(calls),
                    shape_args=all_arg_kinds,
                    verdict=verdict,
                    expansion_form=patch.expansion_form,
                    score=score,
                    error=score.error,
                ))
            except Exception as exc:
                score = ScoreResult(
                    compiled=False,
                    baseline_pct=None,
                    deinlined_pct=None,
                    delta_fuzzy=None,
                    baseline_ndl=None,
                    deinlined_ndl=None,
                    delta_struct=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
                records.append(_record_for(
                    run_id=run_id,
                    function=function,
                    unit=unit,
                    inline_def=inline_def,
                    n_call_sites=len(calls),
                    shape_args=all_arg_kinds,
                    verdict="deinline_failed",
                    expansion_form=patch.expansion_form,
                    score=score,
                    error=score.error,
                ))
        if max_pairs is not None and len(records) >= max_pairs:
            break
    return records


def _record_shape_key(record: LeverageRecord) -> str:
    return "/".join(
        [
            record.shape_return,
            record.shape_body,
            record.expansion_form or "unsupported",
            record.def_location,
        ]
    )


def summarize_records(records: list[LeverageRecord]) -> dict:
    buckets = Counter(record.verdict for record in records)
    scored = buckets["lever"] + buckets["fuzzy_only"] + buckets["neutral"]
    shape_buckets: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        key = _record_shape_key(record)
        shape_buckets[key][record.verdict] += 1
        if record.delta_struct is not None:
            shape_buckets[key]["delta_struct_sum"] += record.delta_struct
    return {
        "total_pairs": len(records),
        "scored_pairs": scored,
        "buckets": {name: buckets.get(name, 0) for name in (
            "lever",
            "fuzzy_only",
            "neutral",
            "unsupported",
            "deinline_failed",
        )},
        "strict_lever_rate": None if scored == 0 else buckets["lever"] / scored,
        "permissive_lever_rate": (
            None if scored == 0 else (buckets["lever"] + buckets["fuzzy_only"]) / scored
        ),
        "shape_buckets": {
            key: dict(value)
            for key, value in sorted(shape_buckets.items())
        },
    }


def _load_report(melee_root: Path) -> dict:
    return json.loads((melee_root / "build" / "GALE01" / "report.json").read_text())


def _source_rel_from_unit(unit_name: str) -> str:
    unit = unit_name.removeprefix("main/")
    return f"src/{unit}.c"


def select_report_functions(
    *,
    melee_root: Path,
    module: str | None,
    function: str | None,
    file_path: Path | None,
    all_modules: bool,
    limit: int,
) -> list[tuple[str, Path]]:
    if file_path is not None:
        source_path = file_path if file_path.is_absolute() else melee_root / file_path
        source_path = source_path.resolve()
        if function is None:
            raise ValueError("--file requires --function for the first slice")
        return [(function, source_path)]
    report = _load_report(melee_root)
    selected: list[tuple[str, Path]] = []
    for unit in report.get("units", []):
        unit_name = str(unit.get("name") or "")
        rel_unit = unit_name.removeprefix("main/")
        if function is not None:
            pass
        elif module is not None:
            if not rel_unit.startswith(f"melee/{module}/"):
                continue
        elif not all_modules:
            raise ValueError("pass --module, --function, --file, or explicit --all")
        source_path = melee_root / _source_rel_from_unit(unit_name)
        for fn in unit.get("functions", []):
            fn_name = fn.get("name")
            if not fn_name:
                continue
            if function is not None and fn_name != function:
                continue
            if function is None and float(fn.get("fuzzy_match_percent") or 0.0) < 100.0:
                continue
            selected.append((fn_name, source_path))
            if len(selected) >= limit:
                return selected
    return selected


def _run_checkdiff(melee_root: Path, function: str, timeout: float) -> dict:
    env = os.environ.copy()
    # The CLI wrapper acquires the same repo-wide lock before real scoring.
    # Avoid self-deadlocking the child checkdiff process on that lock.
    env["CHECKDIFF_NO_LOCK"] = "1"
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "tools/checkdiff.py",
            function,
            "--format",
            "json",
            "--no-tty",
        ],
        cwd=melee_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"checkdiff exited {proc.returncode}")
    return json.loads(proc.stdout)


def _safe_stem(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "inline"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_evidence(
    *,
    evidence_dir: Path,
    function: str,
    inline_name: str,
    original_source: str,
    patched_source: str,
    baseline_payload: dict | None,
    variant_payload: dict | None,
    score: ScoreResult,
) -> dict[str, str]:
    pair_dir = evidence_dir / f"{_safe_stem(function)}__{_safe_stem(inline_name)}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "baseline_source": pair_dir / "baseline_source.c",
        "deinlined_source": pair_dir / "deinlined_source.c",
        "baseline_checkdiff": pair_dir / "baseline_checkdiff.json",
        "deinlined_checkdiff": pair_dir / "deinlined_checkdiff.json",
        "score": pair_dir / "score.json",
        "pcdump_blocker": pair_dir / "pcdump_blocker.json",
    }
    paths["baseline_source"].write_text(original_source)
    paths["deinlined_source"].write_text(patched_source)
    if baseline_payload is not None:
        _write_json(paths["baseline_checkdiff"], baseline_payload)
    if variant_payload is not None:
        _write_json(paths["deinlined_checkdiff"], variant_payload)
    _write_json(paths["score"], {
        "compiled": score.compiled,
        "baseline_pct": score.baseline_pct,
        "deinlined_pct": score.deinlined_pct,
        "delta_fuzzy": score.delta_fuzzy,
        "baseline_ndl": score.baseline_ndl,
        "deinlined_ndl": score.deinlined_ndl,
        "delta_struct": score.delta_struct,
        "error": score.error,
    })
    _write_json(paths["pcdump_blocker"], {
        "status": "not_collected",
        "reason": (
            "inline-leverage scorer is checkdiff-only; pcdump retention requires "
            "a separate debug dump run against the retained deinlined_source.c"
        ),
    })
    return {key: str(path) for key, path in paths.items() if path.exists()}


def make_real_tree_scorer(
    *,
    melee_root: Path,
    source_path: Path,
    function: str,
    timeout: float,
    evidence_dir: Path | None = None,
) -> InlineScorer:
    original = source_path.read_text()
    baseline_payload: dict | None = None

    def score(patched_source: str, inline_name: str) -> ScoreResult:
        nonlocal baseline_payload
        if baseline_payload is None:
            baseline_payload = _run_checkdiff(melee_root, function, timeout)
        source_path.write_text(patched_source)
        variant_payload: dict | None = None
        try:
            variant_payload = _run_checkdiff(melee_root, function, timeout)
        except Exception as exc:
            result = ScoreResult(
                compiled=False,
                baseline_pct=None,
                deinlined_pct=None,
                delta_fuzzy=None,
                baseline_ndl=None,
                deinlined_ndl=None,
                delta_struct=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            source_path.write_text(original)
        if variant_payload is not None:
            result = diff_scores(baseline_payload, variant_payload)
        if evidence_dir is not None:
            result = ScoreResult(
                compiled=result.compiled,
                baseline_pct=result.baseline_pct,
                deinlined_pct=result.deinlined_pct,
                delta_fuzzy=result.delta_fuzzy,
                baseline_ndl=result.baseline_ndl,
                deinlined_ndl=result.deinlined_ndl,
                delta_struct=result.delta_struct,
                error=result.error,
                evidence=_write_evidence(
                    evidence_dir=evidence_dir,
                    function=function,
                    inline_name=inline_name,
                    original_source=original,
                    patched_source=patched_source,
                    baseline_payload=baseline_payload,
                    variant_payload=variant_payload,
                    score=result,
                ),
            )
        return result

    return score


def run_inline_leverage(
    *,
    melee_root: Path,
    module: str | None = None,
    function: str | None = None,
    file_path: Path | None = None,
    all_modules: bool = False,
    limit: int = 20,
    max_pairs: int | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    epsilon: float = 0.05,
    db_path: Path | None = None,
    checkdiff_timeout: float = 600.0,
    evidence_dir: Path | None = None,
) -> dict:
    run_id = run_id or f"inline-leverage-{int(time.time())}"
    targets = select_report_functions(
        melee_root=melee_root,
        module=module,
        function=function,
        file_path=file_path,
        all_modules=all_modules,
        limit=limit,
    )
    records: list[LeverageRecord] = []
    store: InlineLeverageStore | None = None
    if db_path is not None:
        store = InlineLeverageStore(db_path)
        store.ensure_schema()
    include_dirs = [
        melee_root / "include",
        melee_root / "src",
        melee_root / "src" / "melee",
    ]
    remaining_pairs = max_pairs
    for fn_name, source_path in targets:
        if not source_path.is_file():
            continue
        source = source_path.read_text()
        unit = str(source_path.relative_to(melee_root))
        defs = resolve_inline_defs(source_path, include_dirs)
        scorer = None if dry_run else make_real_tree_scorer(
            melee_root=melee_root,
            source_path=source_path,
            function=fn_name,
            timeout=checkdiff_timeout,
            evidence_dir=evidence_dir,
        )
        fn_records = measure_function_source(
            source=source,
            function=fn_name,
            unit=unit,
            run_id=run_id,
            scorer=scorer,
            inline_defs=defs,
            epsilon=epsilon,
            max_pairs=remaining_pairs,
        )
        if store is not None:
            tu_hash = hashlib.sha256(source.encode()).hexdigest()
            for record in fn_records:
                store.insert(record)
                store.mark_seen(tu_hash, record.function, record.inline_name)
        records.extend(fn_records)
        if remaining_pairs is not None:
            remaining_pairs -= len(fn_records)
            if remaining_pairs <= 0:
                break
    return {
        "run_id": run_id,
        "scope": {
            "module": module,
            "function": function,
            "file": None if file_path is None else str(file_path),
            "all": all_modules,
            "dry_run": dry_run,
        },
        "targets": [
            {"function": fn_name, "source": str(path)}
            for fn_name, path in targets
        ],
        "summary": summarize_records(records),
        "records": [record.to_dict() for record in records],
    }


def render_text(report: dict) -> str:
    summary = report["summary"]
    scope = report["scope"]
    scope_label = (
        f"function={scope['function']}"
        if scope.get("function")
        else f"module={scope.get('module') or 'all'}"
    )
    lines = [
        f"inline-leverage ({scope_label}, run={report['run_id']}): "
        f"{summary['total_pairs']} (function,inline) pairs",
    ]
    buckets = summary["buckets"]
    lines.extend([
        f"  lever (strict, structural):    {buckets['lever']}",
        f"  fuzzy_only (backend tie-break): {buckets['fuzzy_only']}",
        f"  neutral:                       {buckets['neutral']}",
        f"  unsupported:                   {buckets['unsupported']}",
        f"  deinline_failed:               {buckets['deinline_failed']}",
    ])
    if summary["strict_lever_rate"] is not None:
        lines.append(f"  strict lever rate:             {summary['strict_lever_rate']:.1%}")
        lines.append(
            f"  permissive lever rate:         {summary['permissive_lever_rate']:.1%}"
        )
    lines.append("")
    lines.append("shape buckets:")
    if not summary["shape_buckets"]:
        lines.append("  (none)")
    for key, bucket in summary["shape_buckets"].items():
        parts = ", ".join(
            f"{name}={bucket.get(name, 0)}"
            for name in ("lever", "fuzzy_only", "neutral", "unsupported", "deinline_failed")
        )
        lines.append(f"  {key}: {parts}")
    if report["records"]:
        lines.append("")
        lines.append("retained evidence:")
        for record in report["records"][:20]:
            error = f" [{record['error']}]" if record.get("error") else ""
            lines.append(
                f"  {record['function']} -> {record['inline_name']}: "
                f"{record['verdict']} {record['shape_return']}/"
                f"{record['shape_body']}/{record.get('expansion_form')}"
                f" calls={record['n_call_sites']} def={record['def_file']}{error}"
            )
    return "\n".join(lines)
