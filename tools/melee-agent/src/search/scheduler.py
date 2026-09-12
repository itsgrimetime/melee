from __future__ import annotations
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from src.search.adapters import CheckdiffVerifier
from src.search.artifact import CandidateArtifact
from src.search.store import ArtifactStore
from src.search.types import (SearchResult, SearchContext, TargetSpec, Budget, SchedulePolicy, SourceSpec, SourceVariant)

if TYPE_CHECKING:
    from src.search.directed.contracts import DirectedSchedulerConfig, DirectedSearchState

class DefaultScheduler:
    def __init__(self, *, store: ArtifactStore, verifier: CheckdiffVerifier | None):
        self._store = store; self._verifier = verifier

    def run(
        self,
        *,
        sources,
        backends,
        producers,
        pipeline,
        target,
        budget,
        policy,
        progress: Callable[[dict], None] | None = None,
        directed: "DirectedSchedulerConfig | None" = None,
    ) -> SearchResult:
        acct = {"compiled": 0, "harvested": 0, "promoted": 0, "compile_failed": 0,
                "score_failed": 0, "deduped": 0, "retried": 0,
                "producer_failed": 0, "producer_drained": 0, "producer_failures": [],
                "producer_started": 0, "producer_polls": 0,
                "producer_no_candidate_polls": 0, "producer_active": 0,
                "producer_stopped": 0, "iterations": 0,
                "source_drained": False,
                "source_drained_names": [],
                "budget_exhausted": False}
        seen: set[str] = set()
        best: list[CandidateArtifact] = []
        matched: CandidateArtifact | None = None
        base = SourceSpec("", target)
        started_at = time.monotonic()

        def emit(event: str, **payload) -> None:
            if progress is None:
                return
            progress({
                "event": event,
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                **payload,
            })

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

        # --- directed-mode state (all behind if directed is not None) ---
        directed_telemetry: list = []
        ctx: SearchContext | None = None
        parent_state: "DirectedSearchState | None" = None
        directed_seen: set[tuple] = set()  # (candidate_id, parent_state_id)

        def _dir_key(a: CandidateArtifact):
            """Rank directed candidates by directed score, then byte score."""
            bs = a.byte_score if a.byte_score is not None else (1 << 30)
            directed_value = a.directed_score
            if directed_value is None and a.directed_meta is not None:
                directed_value = getattr(a.directed_meta, "directed_scalar", None)
            if directed_value is None and a.directed_meta is not None:
                directed_value = getattr(a.directed_meta, "displacement", None)
            directed_rank = (
                -directed_value if directed_value is not None else (1 << 30)
            )
            return (directed_rank, bs)

        if directed is not None:
            from src.search.directed.contracts import DirectedSearchState
            ctx = SearchContext()
            parent_state = DirectedSearchState(
                prev_state=None,
                history=(),
                last_lever=None,
                current_best=None,
                state_id="root",
            )

        handles = []
        for p in producers:
            handle = p.start(base, target, budget)
            for failure in handle.start_failures:
                acct["producer_failed"] += 1
                failure_payload = {
                    "producer": p.name(),
                    "jobs": [],
                    "remote": failure.get("remote", ""),
                    "detail": failure.get("detail", ""),
                }
                acct["producer_failures"].append(failure_payload)
                emit(
                    "producer-start-failed",
                    producer=p.name(),
                    remote=failure_payload["remote"],
                    detail=failure_payload["detail"],
                )
            acct["producer_started"] += len(handle.job_ids)
            if handle.job_ids:
                handles.append((p, handle))
                emit(
                    "producer-started",
                    producer=p.name(),
                    jobs=list(handle.job_ids),
                )
        all_handles = list(handles)
        # deferred: pcdump-capability routing (route_pcdump_to_capable_only /
        # want_pcdump) is tied to the tier-2 directed/pcdump seam — pcdump IS
        # the directed seam, out of scope for Spec 1. Round-robin only here.
        # NOTE: max_iters=0 falls through to a single pass (treated as "run
        # once"); max_seconds is a wall-clock cap enforced below.
        iters = budget.max_iters or 1
        deadline = (time.monotonic() + budget.max_seconds
                    if budget.max_seconds is not None else None)
        for iteration in range(1, iters + 1):
            if deadline is not None and time.monotonic() >= deadline:
                acct["budget_exhausted"] = True
                emit(
                    "budget-exhausted",
                    reason="max_seconds",
                    iteration=iteration,
                    max_iters=iters,
                )
                break
            acct["iterations"] = iteration
            made_progress = False
            for src in sources:
                scored_batch: list[CandidateArtifact] = []
                batch = src.next_batch(policy.batch_size)
                if batch:
                    made_progress = True
                source_drained = bool(getattr(src, "drained", False))
                if source_drained:
                    acct["source_drained"] = True
                    source_name = src.name()
                    if source_name not in acct["source_drained_names"]:
                        acct["source_drained_names"].append(source_name)

                if directed is not None:
                    if not batch:
                        src.observe([])
                        continue
                    # --- DIRECTED MODE: all new behavior behind this guard ---
                    from src.search.directed.contracts import (
                        DirectedScoringCall,
                        DirectedSearchState,
                    )
                    # Step 1: decide escalation BEFORE compiling (so want_pcdump is known)
                    escalate = directed.score_pipeline.should_escalate(None, ctx)
                    active_backend = directed.backend if escalate else backend
                    # Directed dedup uses (candidate_id, parent_state_id) so same
                    # source under different parents is not dropped.
                    current_parent_id = parent_state.state_id

                    dir_batch_candidates: list[CandidateArtifact] = []
                    dir_byte_scored: list[CandidateArtifact] = []  # CURRENT batch only
                    for variant in batch:
                        if active_backend is None:
                            break
                        art = active_backend.compile(variant, want_pcdump=escalate)
                        acct["compiled"] += 1
                        # Directed dedup: (candidate_id, parent_state_id) so the
                        # same source under different parents is not dropped.
                        dedup_key = (art.candidate_id, current_parent_id)
                        if dedup_key in directed_seen:
                            acct["deduped"] += 1
                            continue
                        directed_seen.add(dedup_key)
                        if art.status == "compile_failed":
                            acct["compile_failed"] += 1
                            continue
                        # Byte score via the standard pipeline
                        scored_art = directed.score_pipeline.score_byte(art, target)
                        if scored_art.status == "score_failed":
                            acct["score_failed"] += 1
                            continue
                        # Track this batch's byte-scored artifacts (incl. ones
                        # that will be marked invalid) so the all-invalid
                        # fallback can pick a CURRENT-batch byte-best to mutate
                        # from — never a stale candidate from a prior batch.
                        dir_byte_scored.append(scored_art)
                        # Directed scoring
                        if escalate:
                            call = DirectedScoringCall(directed.objective, parent_state)
                            scored_art = directed.score_pipeline.score_directed(scored_art, call)
                            if scored_art.directed_meta is not None:
                                directed_telemetry.append(scored_art.directed_meta)
                                if not scored_art.directed_meta.valid:
                                    acct["directed_invalid"] = acct.get("directed_invalid", 0) + 1
                                    # invalid → skip from best-selection
                                    continue
                        best.append(scored_art)
                        dir_batch_candidates.append(scored_art)
                        if scored_art.byte_score == 0 and (
                            self._verifier is None
                            or self._verifier.is_match(target.function, scored_art.object_path)
                        ):
                            matched = scored_art

                    # Select exactly ONE best (byte_score asc, then -displacement).
                    if dir_batch_candidates:
                        one_best = min(dir_batch_candidates, key=_dir_key)
                    elif dir_byte_scored:
                        # Every candidate this batch was invalid (but some
                        # compiled+byte-scored): fall back to the CURRENT batch's
                        # byte-best so the source still has something to mutate.
                        one_best = min(dir_byte_scored, key=_dir_key)
                    else:
                        # Nothing compiled this batch.
                        one_best = None

                    if one_best is not None:
                        scored_batch = [one_best]
                        if one_best.byte_score is not None:
                            ctx.byte_history.append(one_best.byte_score)

                    # observe exactly ONE best (not the whole batch)
                    src.observe(scored_batch)

                    # Advance parent_state for the next iteration
                    applied_mutator = (
                        one_best.directed_meta.applied_mutator
                        if (one_best is not None and one_best.directed_meta is not None)
                        else None
                    )
                    next_parent = DirectedSearchState(
                        prev_state=parent_state,
                        history=parent_state.history + (parent_state.state_id,),
                        last_lever=applied_mutator,
                        current_best=one_best,
                        state_id=f"s{iteration}",
                    )
                    # Thread the selected best's directed (phys-match) scalar
                    # onto the next parent so the scorer's displacement_delta is
                    # measured against the real parent's phys-match, not a flat
                    # 0.0. (DirectedSearchState is frozen; set via object.)
                    best_disp = (
                        one_best.directed_meta.displacement
                        if (one_best is not None and one_best.directed_meta is not None)
                        else 0.0
                    )
                    object.__setattr__(next_parent, "displacement", best_disp)
                    parent_state = next_parent
                    if matched:
                        break

                else:
                    # --- TIER-1 (unchanged) path ---
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
                acct["producer_polls"] += 1
                if not harvested:
                    acct["producer_no_candidate_polls"] += 1
                acct["harvested"] += len(harvested)
                if harvested:
                    made_progress = True
                harvested = [h for h in harvested if h.candidate_id not in seen]
                harvested.sort(key=lambda a: (a.producer_score is None, a.producer_score))
                for cand in harvested[: policy.promote_top_k]:
                    variant = SourceVariant(
                        cand.source_blob.read_text(),
                        cand.provenance,
                    )
                    if directed is not None:
                        from src.search.directed.contracts import DirectedScoringCall

                        seen.add(cand.candidate_id)
                        if directed.backend is None:
                            break
                        recompiled = directed.backend.compile(
                            variant,
                            want_pcdump=True,
                        )
                        acct["compiled"] += 1
                        if recompiled.status == "compile_failed":
                            acct["compile_failed"] += 1
                            continue
                        recompiled = replace(
                            recompiled,
                            candidate_id=cand.candidate_id,
                            producer_score=cand.producer_score,
                            provenance=cand.provenance,
                        )
                        scored = directed.score_pipeline.score_byte(
                            recompiled,
                            target,
                        )
                        if scored.status == "score_failed":
                            acct["score_failed"] += 1
                            continue
                        call = DirectedScoringCall(directed.objective, parent_state)
                        scored = directed.score_pipeline.score_directed(scored, call)
                        if scored.directed_meta is not None:
                            directed_telemetry.append(scored.directed_meta)
                            if not scored.directed_meta.valid:
                                acct["directed_invalid"] = (
                                    acct.get("directed_invalid", 0) + 1
                                )
                                continue
                        best.append(scored)
                        acct["promoted"] += 1
                        if scored.byte_score == 0 and (
                            self._verifier is None
                            or self._verifier.is_match(
                                target.function,
                                scored.object_path,
                            )
                        ):
                            matched = scored
                    else:
                        if backend is None:
                            break
                        recompiled = compile_with_retry(variant)
                        recompiled = replace(
                            recompiled,
                            candidate_id=cand.candidate_id,
                            producer_score=cand.producer_score,
                            provenance=cand.provenance,
                        )
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
                    acct["producer_active"] += 1
                    active_handles.append((producer, handle))
                emit(
                    "producer-poll",
                    iteration=iteration,
                    poll=acct["producer_polls"],
                    producer=producer.name(),
                    jobs=list(handle.job_ids),
                    harvested=len(harvested),
                    state=status.state,
                    detail=status.detail,
                )
            handles = active_handles
            if matched: break
            if not handles and not made_progress:
                break
        else:
            if handles and not matched:
                acct["budget_exhausted"] = True
                emit(
                    "budget-exhausted",
                    reason="max_iters",
                    iteration=acct["iterations"],
                    max_iters=iters,
                    active_producers=[
                        {"producer": producer.name(), "jobs": list(handle.job_ids)}
                        for producer, handle in handles
                    ],
                )
        for producer, handle in all_handles:
            producer.stop(handle)
            acct["producer_stopped"] += len(handle.job_ids)
            emit(
                "producer-stopped",
                producer=producer.name(),
                jobs=list(handle.job_ids),
            )
        if directed is not None:
            best.sort(key=_dir_key)
        else:
            best.sort(key=lambda a: (a.byte_score is None, a.byte_score))
        return SearchResult(
            best=best[:25],
            matched=matched,
            accounting=acct,
            directed_telemetry=directed_telemetry,
        )
