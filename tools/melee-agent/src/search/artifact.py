"""Artifact contract: pure dataclasses for search substrate."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class CompileSpec:
    """Specification for compilation context."""

    target_id: str
    cflags_hash: str
    base_context_hash: str
    toolchain_fingerprint: str
    backend_mode: str
    manifest_path: Path


@dataclass(frozen=True)
class CompileManifest:
    """Manifest of compilation artifacts and configuration."""

    compile_command: list[str]
    cflags: list[str]
    include_paths: list[str]
    base_context_blob: Path
    permuter_compile_sh: Path | None = None
    permuter_settings_toml: Path | None = None
    directed_objective: dict | None = None


@dataclass(frozen=True)
class Provenance:
    """Source lineage and metadata for a candidate."""

    source_name: str
    parent_id: str | None
    mutation: str | None
    base_hash: str
    producer_meta: dict


@dataclass(frozen=True)
class CandidateArtifact:
    """Complete artifact describing a match candidate."""

    candidate_id: str
    source_hash: str
    source_blob: Path
    compile_spec: CompileSpec
    object_path: Path | None
    producer_score: float | None
    byte_score: int | None
    directed_score: float | None
    pcdump_path: Path | None
    compiler_stderr: str
    provenance: Provenance
    status: Literal["ok", "harvested", "compile_failed", "score_failed", "invalid"]
    directed_meta: Any = None


def compute_candidate_id(spec: CompileSpec, source_hash: str) -> str:
    """Compute a unique candidate ID from compile context and source hash.

    The ID is deterministic: any change to the compile spec or source hash
    produces a different ID. This ensures candidates are uniquely identified
    and de-duplicated across production runs.
    """
    h = hashlib.sha256()
    for part in (
        spec.target_id,
        spec.cflags_hash,
        spec.base_context_hash,
        spec.toolchain_fingerprint,
        spec.backend_mode,
        source_hash,
    ):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()[:32]
