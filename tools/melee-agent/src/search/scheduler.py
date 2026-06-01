from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from src.search.adapters import CheckdiffVerifier
from src.search.artifact import CandidateArtifact
from src.search.store import ArtifactStore
from src.search.types import (SearchResult, TargetSpec, Budget, SchedulePolicy, SourceSpec, SourceVariant)

class DefaultScheduler:
    def __init__(self, *, store: ArtifactStore, verifier: CheckdiffVerifier | None):
        self._store = store; self._verifier = verifier

    def run(self, *, sources, backends, producers, pipeline, target, budget, policy) -> SearchResult:
        acct = {"compiled": 0, "harvested": 0, "promoted": 0, "compile_failed": 0,
                "score_failed": 0, "deduped": 0}
        seen: set[str] = set()
        best: list[CandidateArtifact] = []
        matched: CandidateArtifact | None = None
        base = SourceSpec("", target)

        def ingest(art: CandidateArtifact) -> CandidateArtifact | None:
            nonlocal matched
            if art.candidate_id in seen:
                acct["deduped"] += 1; return None
            seen.add(art.candidate_id)
            if art.status == "compile_failed": acct["compile_failed"] += 1; return None
            scored = pipeline.score_byte(art, target)
            if scored.status == "score_failed": acct["score_failed"] += 1; return None
            best.append(scored)
            if scored.byte_score == 0 and (self._verifier is None
                    or self._verifier.is_match(target.function, scored.object_path)):
                matched = scored
            return scored

        handles = [(p, p.start(base, target, budget)) for p in producers]
        backend = backends[0] if backends else None
        iters = budget.max_iters or 1
        for _ in range(iters):
            for src in sources:
                for variant in src.next_batch(policy.batch_size):
                    if backend is None: break
                    art = backend.compile(variant); acct["compiled"] += 1
                    ingest(art)
                    if matched: break
            for producer, handle in handles:
                harvested = producer.poll(handle)
                acct["harvested"] += len(harvested)
                harvested = [h for h in harvested if h.candidate_id not in seen]
                harvested.sort(key=lambda a: (a.producer_score is None, a.producer_score))
                for cand in harvested[: policy.promote_top_k]:
                    if backend is None: break
                    recompiled = backend.compile(SourceVariant(cand.source_blob.read_text(), cand.provenance))
                    recompiled = replace(recompiled, candidate_id=cand.candidate_id,
                                         producer_score=cand.producer_score, provenance=cand.provenance)
                    acct["promoted"] += 1; acct["compiled"] += 1
                    ingest(recompiled)
                    if matched: break
            if matched: break
        for producer, handle in handles:
            producer.stop(handle)
        best.sort(key=lambda a: (a.byte_score is None, a.byte_score))
        return SearchResult(best=best[:25], matched=matched, accounting=acct)
