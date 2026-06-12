"""Backends for the search substrate: compile and manage candidates."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from src.search.adapters import LocalCompiler
from src.search.artifact import (
    CandidateArtifact,
    CompileSpec,
    Provenance,
    compute_candidate_id,
)
from src.search.store import ArtifactStore
from src.search.types import SourceVariant, TargetSpec, BackendCaps


class PlainLocalBackend:
    """Simple local compile backend over a LocalCompiler."""

    def __init__(
        self,
        *,
        compiler: LocalCompiler,
        store: ArtifactStore,
        compile_spec_factory: Callable[[SourceVariant], CompileSpec],
        target: TargetSpec | None = None,
    ):
        self._compiler = compiler
        self._store = store
        self._spec_factory = compile_spec_factory
        self._target = target

    def name(self) -> str:
        return "plain-local"

    def capabilities(self) -> BackendCaps:
        return BackendCaps("local", 1, False)

    def compile(
        self, variant: SourceVariant, *, want_pcdump: bool = False
    ) -> CandidateArtifact:
        """Compile a source variant and return a CandidateArtifact."""
        spec = self._spec_factory(variant)
        source_blob = self._store.put_source(variant.source_text)
        source_hash = hashlib.sha256(variant.source_text.encode()).hexdigest()[:32]
        prov = variant.provenance or Provenance("unknown", None, None, "", {})
        cid_override = prov.producer_meta.get("candidate_id_override")
        cid = (
            cid_override
            if isinstance(cid_override, str) and cid_override
            else compute_candidate_id(spec, source_hash)
        )
        obj, stderr = self._compiler.compile(variant.source_text, self._target)
        status = "ok" if obj is not None else "compile_failed"
        return CandidateArtifact(
            cid,
            source_hash,
            source_blob,
            spec,
            obj,
            None,
            None,
            None,
            None,
            stderr,
            prov,
            status,
        )
