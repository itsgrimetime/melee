"""DirectedSource — a VariantSource that vends deterministic mutator candidates.

The source is driven by an injected ``propose`` callable that selects the next
(mutator_key, anchor) pair given the current best source and the set of already-
tried mutator keys.  An injected ``apply`` callable (defaults to
``apply_mutator`` from the mutators module) applies the edit and returns the
new source text, or ``None`` if the edit is not applicable.

Stall tracking:
- ``stalls`` increments whenever ``observe`` receives an empty list OR the
  best displacement in the observed batch does not exceed the current best.
- ``stalls`` resets to 0 whenever a new best displacement is seen.

No-infinite-loop guard: every key returned by ``propose`` is unconditionally
added to ``_tried`` before the apply check, so even if ``propose`` repeats a
key it will be skipped on the next call (the ``key in self._tried: continue``
branch) without re-applying or re-emitting it.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.search.artifact import Provenance
from src.search.types import SourceSpec, SourceVariant


class DirectedSource:
    """Propose-driven VariantSource with stall detection.

    Parameters
    ----------
    propose:
        ``(source_text: str, tried: frozenset[str]) -> (key, anchor) |
        (key, anchor, meta) | None``
        Return ``None`` to signal exhaustion.  The optional 3rd element is a
        dict merged into the variant's ``Provenance.producer_meta`` — used to
        mark a blind/non-actionable proposal (``{"non_actionable": True}``) so
        the gate never counts it as attributed.
    apply:
        ``(key: str, anchor, source_text: str) -> str | None``
        Defaults to :func:`src.search.directed.mutators.apply_mutator`.
        Return ``None`` if the edit is not applicable to the current source.
    """

    def __init__(
        self,
        *,
        propose: Callable,
        apply: Optional[Callable] = None,
    ) -> None:
        self._propose = propose
        if apply is None:
            # Lazy import to avoid a hard dependency at module load time.
            from src.search.directed.mutators import apply_mutator
            self._apply: Callable = apply_mutator
        else:
            self._apply = apply

        # State initialised by seed().
        self._current_best: str = ""
        self._tried: set[str] = set()
        self.stalls: int = 0
        self._best_disp: Optional[float] = None
        self.drained: bool = False

    # ------------------------------------------------------------------
    # VariantSource protocol
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "directed"

    def seed(self, base: SourceSpec) -> None:
        self._current_best = base.base_source
        self._tried = set()
        self.stalls = 0
        self._best_disp = None
        self.drained = False

    def next_batch(self, n: int) -> list[SourceVariant]:
        out: list[SourceVariant] = []
        while len(out) < n:
            p = self._propose(self._current_best, frozenset(self._tried))
            if p is None:
                self.drained = True
                break
            # propose may return (key, anchor) or (key, anchor, meta).
            if len(p) == 3:
                key, anchor, prop_meta = p
            else:
                key, anchor = p
                prop_meta = {}
            # No-infinite-loop guard: skip (but do NOT re-add) already-tried keys.
            if key in self._tried:
                continue
            # Mark tried unconditionally before apply so un-appliable edits are
            # never retried either.
            self._tried.add(key)
            text = self._apply(key, anchor, self._current_best)
            if text is None:
                # Edit not applicable — skip emission but keep in tried set.
                continue
            out.append(
                SourceVariant(
                    source_text=text,
                    provenance=Provenance(
                        source_name="directed",
                        parent_id=None,
                        mutation=key,
                        base_hash="",
                        producer_meta=dict(prop_meta) if prop_meta else {},
                    ),
                )
            )
        return out

    def observe(self, scored: list) -> None:  # list[CandidateArtifact]
        if not scored:
            self.stalls += 1
            return

        # Pick the best candidate: lowest byte_score (more matched bytes), then
        # highest displacement (closer to target).
        def _sort_key(a):
            byte = a.byte_score if a.byte_score is not None else (1 << 30)
            disp = -(a.directed_meta.displacement if a.directed_meta else 0.0)
            return (byte, disp)

        best = min(scored, key=_sort_key)
        cur = best.directed_meta.displacement if best.directed_meta else None

        if cur is not None and (self._best_disp is None or cur > self._best_disp):
            # Improvement: update best displacement and possibly the source text.
            self._best_disp = cur
            self.stalls = 0
            if best.source_blob is not None:
                self._current_best = best.source_blob.read_text()
        else:
            self.stalls += 1
