"""End-to-end manifest persistence + round-trip through the live CLI path.

Spec §3.1: the manifest is the substrate's single most important contract.
A shipped artifact's CompileSpec.manifest_path must point at a persisted
manifest that read_manifest can recover (cflags + include paths + command).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import (
    _CFLAGS,
    _resolve_include_paths,
    _compute_melee_root,
    search_app,
)
from src.search.artifact import CompileManifest
from src.search.store import ArtifactStore


def _manifest_path_without_writing(store: ArtifactStore, man: CompileManifest) -> Path:
    """Compute the content-addressed manifest path WITHOUT creating the file.

    Mirrors ArtifactStore.put_manifest's serialization so the test can assert
    the CLI persisted the manifest, rather than the test creating it itself.
    """
    import json
    from dataclasses import asdict

    payload = asdict(man)
    for k, v in payload.items():
        if isinstance(v, Path):
            payload[k] = str(v)
    blob = json.dumps(payload, sort_keys=True).encode()
    return store.root / "manifests" / f"{store._addr(blob)}.json"


def test_dry_run_persists_roundtrippable_manifest(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")

    runner = CliRunner()
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(store_dir),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, result.output

    # Reconstruct the SAME content-addressed manifest the CLI builds from the
    # same inputs WITHOUT writing it, then assert the CLI already persisted it.
    melee_root = _compute_melee_root()
    store = ArtifactStore(store_dir)
    base_blob_text = seed.read_text()  # single seed -> the base context blob
    # store.put_source is idempotent (content-addressed); needed so the
    # manifest's base_context_blob path matches the CLI's.
    base_blob = store.put_source(base_blob_text)
    expected_manifest = CompileManifest(
        compile_command=["ninja", "build/GALE01/src/quatlib.o"],
        cflags=_CFLAGS.split(),
        include_paths=_resolve_include_paths(melee_root, "quatlib"),
        base_context_blob=base_blob,
    )
    manifest_path = _manifest_path_without_writing(store, expected_manifest)

    # The artifact's manifest_path must EXIST on disk after the run — i.e. the
    # CLI (not this test) persisted it during the live path.
    assert manifest_path.exists(), (
        f"manifest not persisted by the CLI at {manifest_path}"
    )

    # ...and read_manifest must recover the cflags + include paths + command.
    recovered = store.read_manifest(manifest_path)
    assert recovered.cflags == _CFLAGS.split()
    assert recovered.include_paths == _resolve_include_paths(melee_root, "quatlib")
    assert recovered.compile_command == ["ninja", "build/GALE01/src/quatlib.o"]

    # base_context_hash stamped into the spec must equal the hash of the SAME
    # blob the manifest stores (compute_candidate_id <-> manifest consistency).
    expected_base_hash = hashlib.sha256(base_blob_text.encode()).hexdigest()[:32]
    assert recovered.base_context_blob == base_blob
    assert hashlib.sha256(
        recovered.base_context_blob.read_text().encode()
    ).hexdigest()[:32] == expected_base_hash
