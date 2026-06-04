"""CLI for the search substrate: `melee-agent debug search run`.

Register under debug_app via: debug_app.add_typer(search_app, name="search")
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from itertools import combinations
from pathlib import Path
from typing import Annotated, Optional

import typer

search_app = typer.Typer(
    help="Fast+directed match-search substrate (Spec 1).",
    no_args_is_help=True,
)

# Canonical mwcc cflags used by the project (see CLAUDE.md "Notes").
_CFLAGS = (
    "-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off "
    "-enum int -fp_contract on -inline auto"
)


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
        value = value[len(prefix):]
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
        value = value[len("class"):]
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
    force_phys: dict[int, int] = {}
    class_id: int | None = None
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
                    "expected class_id:ig_idx:phys, ig_idx:phys, "
                    "or class0:ig58:phys=r4"
                )
        except ValueError as exc:
            raise ValueError(
                f"invalid --directed-force-phys entry {spec!r}: {exc}"
            ) from exc
        if class_id is None:
            class_id = entry_class
        elif entry_class != class_id:
            raise ValueError(
                "--directed-force-phys currently supports one register "
                f"class per run; saw class {class_id} and {entry_class}"
            )
        force_phys[ig_idx] = phys
    if not force_phys:
        raise ValueError("--directed-force-phys did not contain any entries")
    return force_phys, (default_class_id if class_id is None else class_id)


def _format_directed_force_phys(force_phys: dict[int, int], class_id: int) -> str:
    return ",".join(
        f"{class_id}:{ig_idx}:{phys}"
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
        raise typer.BadParameter(
            f"candidate spec {raw!r} has an empty candidate id"
        )
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
    return [
        dict(entry) for entry in telemetry
        if isinstance(entry, dict)
    ]


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


def _transform_plan_payload(plan, probes, *, write_dir: Path | None = None) -> dict:
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
        result for result in (validation_results or [])
        if result.get("outcome") == "retained-source-improvement"
    ]
    negative_results = [
        result for result in (validation_results or [])
        if result.get("outcome") == "negative-evidence"
    ]
    refactor_results = [
        result for result in (validation_results or [])
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
        retained_ids = ",".join(str(result.get("probe_id")) for result in retained_results)
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
            f"transform-plan larger-refactor clusters={clusters} "
            f"families={family_ids}"
        )
        if refactor_note:
            note += f" {refactor_note}"
    elif validation_results and negative_results:
        outcome = "blocked"
        retained = False
        blocker = "transform-plan validation exhausted probes with negative evidence"
        note = (
            f"transform-plan negative-evidence probes={len(negative_results)} "
            f"clusters={clusters} families={family_ids}"
        )
        if movement_note:
            note += f" {movement_note}"
    elif probes:
        outcome = "neutral"
        retained = False
        blocker = ""
        note = (
            f"transform-plan probes={len(probes)} clusters={clusters} "
            f"families={family_ids}"
        )
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


def _classify_validation_result(
    returncode: int,
    stdout: str,
    stderr: str,
    payload: dict | None = None,
) -> str:
    if payload:
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
            results.append({
                "probe_id": probe.get("probe_id"),
                "family_id": probe.get("family_id"),
                "outcome": "blocked",
                "returncode": None,
                "command": None,
                "stdout": "",
                "stderr": "candidate_path missing; pass --write-probes",
            })
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
        }
        result["evidence"] = _transform_validation_evidence(
            probe,
            result,
        )
        results.append(result)
        if stop_on_retained and outcome == "retained-source-improvement":
            break
    return results


def _transform_validation_evidence(probe: dict, result: dict) -> dict:
    return {
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
        if probe.get("probe_id") is not None and str(probe.get("probe_id")) not in evaluated_set
    ]
    if not probe_payloads:
        stop_condition = "no-probes"
    elif outcomes.get("retained-source-improvement"):
        stop_condition = "retained-source-improvement"
    elif outcomes.get("larger-refactor-recommended"):
        stop_condition = "larger-refactor-recommended"
    elif validation_results and all(
        result.get("outcome") == "negative-evidence"
        for result in validation_results
    ):
        stop_condition = "exhausted-negative-evidence"
    elif validation_results and all(
        result.get("outcome") == "blocked"
        for result in validation_results
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
    return {
        "stop_condition": stop_condition,
        "evaluated_probes": len(validation_results),
        "remaining_probe_ids": remaining_ids,
        "outcomes": outcomes,
        "evidence_counts": evidence_counts,
    }


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


@search_app.command("plan-transforms")
def plan_transforms_cmd(
    function: Annotated[str, typer.Option("--function", "-f", help="Function to plan for.")],
    unit: Annotated[str, typer.Option("--unit", "-u", help="Translation unit path, e.g. melee/ft/ftcommon.")],
    force_phys: Annotated[
        str,
        typer.Option(
            "--force-phys",
            "--directed-force-phys",
            help="Force-phys proof vector as IG:PHYS or CLASS:IG:PHYS entries.",
        ),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            "--source",
            help="Optional C source file used to instantiate concrete probes.",
        ),
    ] = None,
    max_per_family: Annotated[
        int,
        typer.Option("--max-per-family", help="Maximum materialized probes per family."),
    ] = 3,
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
        generate_transform_probes,
        plan_transform_experiments,
    )

    melee_root = _compute_melee_root()
    try:
        force_phys_map, _class_id = _parse_directed_force_phys(force_phys)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    plan = plan_transform_experiments(
        function=function,
        unit=unit,
        force_phys=force_phys_map,
    )
    probes = ()
    source_path = _resolve_source_file(source_file, melee_root=melee_root)
    if source_path is not None:
        probes = generate_transform_probes(
            source_path.read_text(),
            function=function,
            unit=unit,
            force_phys=force_phys_map,
            max_per_family=max_per_family,
        )

    payload = _transform_plan_payload(plan, probes, write_dir=write_probes)
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
            f"  - {family.family_id}: {family.label} "
            f"(risk: {family.semantic_risk})"
        )
    typer.echo(f"Materialized probes: {len(payload['probes'])}")
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
            f"Ledger: {record['outcome']} "
            f"(attempt {record.get('attempt_index')})"
        )


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
        deltas.append({
            "hunk": idx,
            "tag": tag,
            "base_lines": [i1 + 1, i2],
            "candidate_lines": [j1 + 1, j2],
            "kind": _classify_source_delta(removed, added),
            "removed": removed[:8],
            "added": added[:8],
            "removed_count": len(removed),
            "added_count": len(added),
        })
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
        hunks.append({
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
        })
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
            "--range must look like CANDIDATE_ID:BASE_START-BASE_END="
            "CANDIDATE_START-CANDIDATE_END"
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
    if out["base_end"] < out["base_start"]:
        raise typer.BadParameter("--range base end must be >= base start")
    if out["candidate_end"] < out["candidate_start"]:
        raise typer.BadParameter("--range candidate end must be >= candidate start")
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
                f"--range for {candidate_id} references base line "
                f"{base_end}, but base has {len(base_lines)} line(s)"
            )
        if candidate_end > len(candidate_lines):
            raise typer.BadParameter(
                f"--range for {candidate_id} references candidate line "
                f"{candidate_end}, but candidate has {len(candidate_lines)} line(s)"
            )
        removed = base_lines[base_start:base_end]
        added = candidate_lines[candidate_start:candidate_end]
        hunks.append({
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
        })
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
        for other in ordered[idx + 1:]:
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
        suggestions.append(
            "Drop preprocessor line markers before retaining the edit."
        )
    if "generated-temp-name" in artifacts:
        suggestions.append(
            "Rename generated temporaries to source-meaningful locals and keep "
            "only the lifetime/definition movement they caused."
        )
    if "unnatural-goto-label" in artifacts:
        suggestions.append(
            "Remove generated control-flow scaffolding; naturalize it as a "
            "structured if/loop shape before re-scoring."
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
            "Treat early flag/reload edits as one cluster; single-temp probes "
            "may lose the allocator movement."
        )
    if any("late x594" in cluster for cluster in clusters):
        suggestions.append(
            "Treat late x594 and loop/tree-pointer edits as one cluster before "
            "judging byte-score recovery."
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
            None if meta is None
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
        "hunks": manual_hunks or _source_hunks(
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
    merged_text = _merge_source_hunks(base_text, hunks)
    if merged_text is None:
        return {
            "parents": parents,
            "status": "skipped",
            "reason": "overlapping-source-hunks",
            "clusters": clusters,
            "attribution": _combination_attribution(clusters, parents),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = _combined_candidate_id(parents, merged_text)
    out_path = out_dir / f"{candidate_id}.c"
    out_path.write_text(merged_text)
    return {
        "candidate_id": candidate_id,
        "parents": parents,
        "status": "ok",
        "path": str(out_path),
        "source_hash": _source_hash(merged_text),
        "applied_hunks": [
            _hunk_summary(hunk)
            for hunk in hunks
        ],
        "assignment_union": _combined_assignment_progress(
            [left["meta"], right["meta"]]
        ),
        "clusters": clusters,
        "attribution": _combination_attribution(clusters, parents),
        "score_result": _run_triage_score_command(
            score_command,
            candidate_path=out_path,
        ),
    }


def _meta_to_dict(meta) -> dict:
    if is_dataclass(meta):
        return asdict(meta)
    return dict(meta)


def _parse_assignment_spec(raw: str) -> tuple[int, int]:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) != 2:
        raise typer.BadParameter(
            "--preserve-assignment must look like IG:PHYS, e.g. 42:3"
        )
    try:
        return (
            _parse_directed_int(parts[0], prefix="ig"),
            _parse_directed_phys(parts[1]),
        )
    except ValueError as exc:
        raise typer.BadParameter(
            f"invalid --preserve-assignment {raw!r}: {exc}"
        ) from exc


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
    return keys


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
                "Candidate source file, or CANDIDATE_ID=path. May be passed "
                "multiple times."
            ),
        ),
    ] = None,
    telemetry: Annotated[
        Optional[Path],
        typer.Option(
            "--telemetry",
            help=(
                "JSON from debug search run/directed containing "
                "directed_telemetry."
            ),
        ),
    ] = None,
    score_command: Annotated[
        Optional[str],
        typer.Option(
            "--score-command",
            help=(
                "Optional command template to score each candidate. Use "
                "{candidate} as the source path placeholder."
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
            _parse_triage_candidate(spec)
            for spec in candidate_specs
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
            typer.echo(
                "  satisfied: " + ", ".join(progress["satisfied"])
            )
        if progress["blocked"]:
            typer.echo("  blocked: " + ", ".join(progress["blocked"]))
        if progress["abstained"]:
            typer.echo("  abstained: " + ", ".join(progress["abstained"]))
        if result["assignment_clusters"]:
            typer.echo(
                "  clusters: " + "; ".join(result["assignment_clusters"])
            )
        if result["generated_artifacts"]:
            typer.echo(
                "  generated artifacts: "
                + ", ".join(result["generated_artifacts"])
            )
        typer.echo("  source deltas:")
        for delta in result["source_deltas"]:
            typer.echo(
                f"    - {delta['kind']} "
                f"(+{delta['added_count']} / -{delta['removed_count']})"
            )
        typer.echo("  naturalization:")
        for suggestion in result["naturalization_suggestions"]:
            typer.echo(f"    - {suggestion}")
        score_result = result.get("score_result")
        if score_result is not None:
            typer.echo(
                "  score command: "
                f"returncode={score_result['returncode']}"
            )


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
                "Candidate source file, or CANDIDATE_ID=path. May be passed "
                "multiple times."
            ),
        ),
    ] = None,
    telemetry: Annotated[
        Optional[Path],
        typer.Option(
            "--telemetry",
            help=(
                "JSON from debug search run/directed containing "
                "directed_telemetry."
            ),
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
    manual_ranges = [
        _parse_manual_range(spec)
        for spec in (manual_range_specs or [])
    ]
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
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"Base: {base}")
    typer.echo(f"Telemetry entries: {len(telemetry_entries)}")
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
        typer.echo(f"  output: {combo['path']}")
        progress = combo["assignment_union"]
        if progress["satisfied"]:
            typer.echo(
                "  satisfied union: " + ", ".join(progress["satisfied"])
            )
        if combo.get("score_result") is not None:
            typer.echo(
                "  score command: "
                f"returncode={combo['score_result']['returncode']}"
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
                "Manual subhunk range CANDIDATE_ID:BASE_START-BASE_END="
                "CANDIDATE_START-CANDIDATE_END. May be repeated."
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
    manual_ranges = [
        _parse_manual_range(spec)
        for spec in (manual_range_specs or [])
    ]
    loaded = _load_combine_candidate(
        spec=candidate,
        base_text=base_text,
        telemetry=[],
        manual_ranges=manual_ranges,
    )
    hunks = list(loaded["hunks"])
    if not hunks:
        raise typer.BadParameter("candidate has no source hunks to minimize")
    required = {
        _parse_assignment_spec(spec)
        for spec in (preserve_assignments or [])
    }

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
        "required_assignments": [
            f"ig{ig}->r{phys}" for ig, phys in sorted(required)
        ],
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
    typer.echo(
        "preserved: "
        + ", ".join(payload["required_assignments"])
    )


def _derive_directed_force_phys_from_diff(
    *,
    function: str,
    melee_root: Path,
    verify: bool,
    checkdiff_timeout: float,
    force_vector_probes: bool,
    default_class_id: int,
) -> tuple[dict[int, int], int, dict]:
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
    force_phys_csv = payload.get("force_phys_csv") or ""
    force_phys, class_id = _parse_directed_force_phys(
        force_phys_csv,
        default_class_id=default_class_id,
    )
    if verify:
        verify_payload = payload.get("force_vector_verify") or {}
        union = verify_payload.get("union") if isinstance(verify_payload, dict) else None
        if not verify_payload.get("ran") or not isinstance(union, dict):
            raise RuntimeError(
                "directed force-vector verification did not run: "
                f"{verify_payload.get('reason', 'no union probe')}"
            )
        if not union.get("match"):
            raise RuntimeError(
                "directed force-vector union did not match "
                f"(status={union.get('status')}, returncode={union.get('returncode')})"
            )
    return force_phys, class_id, payload


@search_app.command("run")
def run_cmd(
    function: Annotated[str, typer.Option("--function", "-f", help="Function name to search for.")],
    unit: Annotated[str, typer.Option("--unit", "-u", help="Translation unit path (e.g. melee/gr/quatlib).")],
    store: Annotated[
        Optional[Path],
        typer.Option("--store", help="Artifact store directory. Defaults to build/search-store."),
    ] = None,
    seeds: Annotated[
        Optional[list[str]],
        typer.Option(
            "--seed",
            help=(
                "Seed source files (.c), optionally ID=path. "
                "May be passed multiple times."
            ),
        ),
    ] = None,
    no_remote: Annotated[
        bool,
        typer.Option("--no-remote/--remote", help="Skip remote permuter producers."),
    ] = False,
    remotes: Annotated[
        str,
        typer.Option("--remotes", help="Comma-separated remote names (default: coder1,coder2,coder3)."),
    ] = "coder1,coder2,coder3",
    max_iters: Annotated[
        int,
        typer.Option("--max-iters", help="Maximum scheduler iterations."),
    ] = 10,
    dry_compiler: Annotated[
        bool,
        typer.Option("--dry-compiler", help="Use stub compiler (no real mwcc/wibo). For testing."),
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
                "Derive the directed force-phys proof from "
                "`debug target force-phys-from-diff` before running."
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
                "With --directed-from-diff --verify, include singleton and "
                "prefix force-vector diagnostic probes."
            ),
        ),
    ] = True,
    directed_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--directed-checkdiff-timeout",
            help=(
                "Timeout in seconds for directed proof derivation and "
                "force-vector verification checkdiff runs."
            ),
        ),
    ] = 60.0,
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
    except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
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
                if directed_derivation_payload is not None else None
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
    for raw_seed in (seeds or []):
        candidate_id, seed_path = _parse_run_seed(raw_seed, melee_root=melee_root)
        seed_text = seed_path.read_text(encoding="utf-8")
        seed_texts.append(seed_text)
        seed_variants.append((candidate_id, seed_text))
        seed_entries.append({
            "candidate_id": candidate_id,
            "path": str(seed_path),
            "source_hash": _source_hash(seed_text),
        })
    source = SeedListSource(seed_variants)
    base_seed_text = seed_texts[0] if seed_texts else None
    tu_source_path = melee_root / "src" / f"{unit}.c"
    baseline_source_text = (
        tu_source_path.read_text(encoding="utf-8")
        if tu_source_path.exists() else None
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
        "ninja", obj_rel,
    ]
    manifest = CompileManifest(
        compile_command=compile_command,
        cflags=cflags_list,
        include_paths=include_paths,
        base_context_blob=base_context_blob,
        permuter_compile_sh=(
            remote_ready_permuter_dir / "compile.sh"
            if remote_ready_permuter_dir is not None else None
        ),
        permuter_settings_toml=(
            remote_ready_permuter_dir / "settings.toml"
            if remote_ready_permuter_dir is not None else None
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
            if reason != "case_abstained":
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
        directed_summary = {
            **(directed_manifest or {}),
            "baseline_source_hash": objective.baseline_source_hash,
            "baseline_pcdump_path": (
                str(objective.baseline_pcdump_path)
                if objective.baseline_pcdump_path is not None else None
            ),
            "objective_iter_by_original_ig": {
                str(ig_idx): iter_idx
                for ig_idx, iter_idx
                in sorted(objective.objective_iter_by_original_ig.items())
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
        sources=[source],
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
            m.displacement for m in result.directed_telemetry
            if getattr(m, "valid", False) and getattr(m, "displacement", None) is not None
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


@search_app.command("directed")
def directed_cmd(
    function: Annotated[str, typer.Option("--function", "-f", help="Function name to match.")],
    unit: Annotated[str, typer.Option("--unit", "-u", help="Translation unit path (e.g. melee/gr/gricemt).")],
    store: Annotated[
        Optional[Path],
        typer.Option("--store", help="Artifact store directory. Defaults to build/directed-store."),
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
        typer.Option("--dry/--no-dry", help="Use in-memory fakes; no mwcc runs. For testing."),
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
                "Directed force-phys proof vector, e.g. "
                "0:58:4,0:44:4 or class0:ig58:phys=r4."
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
    class_id = directed_class
    if directed_force_phys and directed_from_diff:
        typer.echo(
            "error: pass either --directed-force-phys or --directed-from-diff, not both",
            err=True,
        )
        raise typer.Exit(2)
    try:
        if directed_force_phys:
            proof_force_phys, class_id = _parse_directed_force_phys(
                directed_force_phys,
                default_class_id=directed_class,
            )
        elif directed_from_diff:
            proof_force_phys, class_id, _payload = _derive_directed_force_phys_from_diff(
                function=function,
                melee_root=melee_root,
                verify=directed_verify,
                checkdiff_timeout=directed_checkdiff_timeout,
                force_vector_probes=False,
                default_class_id=directed_class,
            )
    except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        typer.echo(f"error: directed objective setup failed: {exc}", err=True)
        raise typer.Exit(2) from exc

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
                        return melee_root / "build" / "GALE01" / "obj" / f"{unit_name}.o"
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
