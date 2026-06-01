"""CLI for the search substrate: `melee-agent debug search run`.

Register under debug_app via: debug_app.add_typer(search_app, name="search")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

search_app = typer.Typer(
    help="Fast+directed match-search substrate (Spec 1).",
    no_args_is_help=True,
)


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
    from src.search.artifact import CompileSpec
    from src.search.backends import PlainLocalBackend
    from src.search.producers import PermuterJobProducer
    from src.search.scheduler import DefaultScheduler
    from src.search.scoring import ByteScorePipeline, DefaultSchedulePolicy
    from src.search.sources import SeedListSource
    from src.search.store import ArtifactStore
    from src.search.types import Budget, TargetSpec

    # Resolve melee root (two levels up from tools/melee-agent)
    melee_root = Path(__file__).resolve().parents[3]

    # Resolve expected .o path from report.json
    expected_obj = _resolve_expected_obj(melee_root, function, unit)

    target = TargetSpec(function=function, unit=unit, expected_obj=expected_obj)

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

    # Backend
    _CFLAGS = "-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off -enum int -fp_contract on -inline auto"

    def _make_compile_spec(variant) -> CompileSpec:
        import hashlib as _hashlib
        from src.search.artifact import CompileSpec
        cflags_hash = _hashlib.sha256(_CFLAGS.encode()).hexdigest()[:16]
        return CompileSpec(
            target_id=f"{function}@{unit}",
            cflags_hash=cflags_hash,
            base_context_hash="",
            toolchain_fingerprint="mwcc_233_163n",
            backend_mode="plain-local",
            manifest_path=store / "manifest.json",
        )

    backend = PlainLocalBackend(
        compiler=compiler,
        store=artifact_store,
        compile_spec_factory=_make_compile_spec,
        target=target,
    )

    # Sources
    seed_texts: list[str] = []
    for seed_path in (seeds or []):
        if seed_path.exists():
            seed_texts.append(seed_path.read_text())
        else:
            typer.echo(f"[warn] seed file not found: {seed_path}", err=True)
    source = SeedListSource(seed_texts)

    # Producers
    producers = []
    if not no_remote and not dry_compiler:
        remote_list = [r.strip() for r in remotes.split(",") if r.strip()]
        if remote_list:
            client = RealRemotePermuterClient(melee_root)

            def _make_prod_spec(text: str) -> CompileSpec:
                import hashlib as _hashlib
                from src.search.artifact import CompileSpec
                cflags_hash = _hashlib.sha256(_CFLAGS.encode()).hexdigest()[:16]
                return CompileSpec(
                    target_id=f"{function}@{unit}",
                    cflags_hash=cflags_hash,
                    base_context_hash="",
                    toolchain_fingerprint="mwcc_233_163n",
                    backend_mode="permuter-job",
                    manifest_path=store / "manifest.json",
                )

            producers.append(
                PermuterJobProducer(
                    client=client,
                    store=artifact_store,
                    remotes=remote_list,
                    compile_spec_factory=_make_prod_spec,
                )
            )

    # Pipeline + scheduler
    pipeline = ByteScorePipeline(scorer)
    policy = DefaultSchedulePolicy()
    budget = Budget(max_iters=max_iters)
    scheduler = DefaultScheduler(store=artifact_store, verifier=verifier)

    result = scheduler.run(
        sources=[source],
        backends=[backend],
        producers=producers,
        pipeline=pipeline,
        target=target,
        budget=budget,
        policy=policy,
    )

    summary = {
        "function": function,
        "unit": unit,
        "matched": result.matched is not None,
        "best_byte_score": (
            result.best[0].byte_score if result.best else None
        ),
        "candidates": len(result.best),
        "accounting": result.accounting,
    }
    typer.echo(json.dumps(summary, indent=2))


@search_app.command("status")
def status_cmd() -> None:
    """Show status of the search substrate (store, config)."""
    typer.echo("search substrate: ready")


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
                        return melee_root / "build" / "GALE01" / "src" / f"{unit_name}.o"
        except Exception:
            pass

    # Fallback: derive from unit arg
    return melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
