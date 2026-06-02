from __future__ import annotations
import time
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
                "score_failed": 0, "deduped": 0, "retried": 0,
                "producer_failed": 0, "producer_drained": 0, "producer_failures": []}
        seen: set[str] = set()
        best: list[CandidateArtifact] = []
        matched: CandidateArtifact | None = None
        base = SourceSpec("", target)

        backend = backends[0] if backends else None

        def compile_with_retry(variant: SourceVariant) -> CandidateArtifact:
            """Compile `variant`, retrying a transient compile_failed up to
            policy.max_retries times (bounded retry per spec §3.6-P3)."""
            art = backend.compile(variant); acct["compiled"] += 1
            attempts = 0
            while art.status == "compile_failed" and attempts < policy.max_retries:
                attempts += 1
                art = backend.compile(variant)
                acct["compiled"] += 1; acct["retried"] += 1
            return art

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
        all_handles = list(handles)
        # deferred: pcdump-capability routing (route_pcdump_to_capable_only /
        # want_pcdump) is tied to the tier-2 directed/pcdump seam — pcdump IS
        # the directed seam, out of scope for Spec 1. Round-robin only here.
        # NOTE: max_iters=0 falls through to a single pass (treated as "run
        # once"); max_seconds is a wall-clock cap enforced below.
        iters = budget.max_iters or 1
        deadline = (time.monotonic() + budget.max_seconds
                    if budget.max_seconds is not None else None)
        for _ in range(iters):
            if deadline is not None and time.monotonic() >= deadline:
                break
            made_progress = False
            for src in sources:
                scored_batch: list[CandidateArtifact] = []
                batch = src.next_batch(policy.batch_size)
                if batch:
                    made_progress = True
                for variant in batch:
                    if backend is None: break
                    art = compile_with_retry(variant)
                    s = ingest(art)
                    if s is not None:
                        scored_batch.append(s)
                    if matched: break
                # observe once per drained source batch (spec §3.6-P3)
                src.observe(scored_batch)
                if matched: break
            active_handles = []
            for producer, handle in handles:
                harvested = producer.poll(handle)
                acct["harvested"] += len(harvested)
                if harvested:
                    made_progress = True
                harvested = [h for h in harvested if h.candidate_id not in seen]
                harvested.sort(key=lambda a: (a.producer_score is None, a.producer_score))
                for cand in harvested[: policy.promote_top_k]:
                    if backend is None: break
                    recompiled = compile_with_retry(
                        SourceVariant(cand.source_blob.read_text(), cand.provenance))
                    recompiled = replace(recompiled, candidate_id=cand.candidate_id,
                                         producer_score=cand.producer_score, provenance=cand.provenance)
                    acct["promoted"] += 1
                    ingest(recompiled)
                    if matched: break
                status = producer.status(handle)
                if status.state == "failed":
                    acct["producer_failed"] += 1
                    acct["producer_failures"].append({
                        "producer": producer.name(),
                        "jobs": list(handle.job_ids),
                        "detail": status.detail,
                    })
                elif status.state == "drained":
                    acct["producer_drained"] += 1
                else:
                    active_handles.append((producer, handle))
            handles = active_handles
            if matched: break
            if not handles and not made_progress:
                break
        for producer, handle in all_handles:
            producer.stop(handle)
        best.sort(key=lambda a: (a.byte_score is None, a.byte_score))
        return SearchResult(best=best[:25], matched=matched, accounting=acct)
