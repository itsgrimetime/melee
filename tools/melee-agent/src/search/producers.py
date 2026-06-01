from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Callable
from src.search.adapters import RemotePermuterClient
from src.search.artifact import CandidateArtifact, CompileSpec, Provenance, compute_candidate_id
from src.search.store import ArtifactStore
from src.search.types import SourceSpec, TargetSpec, Budget, ProducerHandle, ProducerStatus

class PermuterJobProducer:
    def __init__(self, *, client: RemotePermuterClient, store: ArtifactStore,
                 remotes: list[str], compile_spec_factory: Callable[[str], CompileSpec]):
        self._client = client; self._store = store
        self._remotes = remotes; self._spec_factory = compile_spec_factory
        self._seen: set[str] = set()

    def name(self) -> str: return "permuter-job"

    def start(self, base: SourceSpec, target: TargetSpec, budget: Budget) -> ProducerHandle:
        base_dir = self._store.root / "permuter-bases" / target.function
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "base.c").write_text(base.base_source)
        job_ids = [self._client.submit(base_dir, target.function, r) for r in self._remotes]
        return ProducerHandle(self.name(), job_ids)

    def poll(self, handle: ProducerHandle) -> list[CandidateArtifact]:
        out: list[CandidateArtifact] = []
        for jid in handle.job_ids:
            for src_path, producer_score in self._client.fetch(jid):
                text = Path(src_path).read_text()
                shash = hashlib.sha256(text.encode()).hexdigest()[:32]
                spec = self._spec_factory(text)
                cid = compute_candidate_id(spec, shash)
                if cid in self._seen:
                    continue
                self._seen.add(cid)
                blob = self._store.put_source(text)
                prov = Provenance("permuter-job", None, None, "base",
                                  {"job_id": jid, "permuter_score": producer_score})
                out.append(CandidateArtifact(cid, shash, blob, spec, None, producer_score,
                                             None, None, None, "", prov, "harvested"))
        return out

    def status(self, handle: ProducerHandle) -> ProducerStatus:
        states = {self._client.status(j) for j in handle.job_ids}
        if "running" in states: return ProducerStatus("running")
        if states == {"drained"}: return ProducerStatus("drained")
        return ProducerStatus("failed", detail=",".join(sorted(states)))

    def stop(self, handle: ProducerHandle) -> None:
        for jid in handle.job_ids:
            self._client.stop(jid)
