"""CLI for the search substrate: `melee-agent debug search run`.

Register under debug_app via: debug_app.add_typer(search_app, name="search")
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, is_dataclass
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


def _meta_to_dict(meta) -> dict:
    if is_dataclass(meta):
        return asdict(meta)
    return dict(meta)


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
        Optional[list[Path]],
        typer.Option("--seed", help="Seed source files (.c). May be passed multiple times."),
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

    # Sources — load seed texts first; they form the base context blob that
    # the manifest records and that base_context_hash is derived from.
    seed_texts: list[str] = []
    for seed_path in (seeds or []):
        if seed_path.exists():
            seed_texts.append(seed_path.read_text())
        else:
            typer.echo(f"[warn] seed file not found: {seed_path}", err=True)
    source = SeedListSource(seed_texts)
    base_seed_text = seed_texts[0] if seed_texts else None
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
                baseline_source_text=base_seed_text,
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
