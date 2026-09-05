"""SourceVariant generators for search substrate."""

from __future__ import annotations

from typing import Sequence

from src.search.types import SourceVariant, SourceSpec
from src.search.artifact import Provenance


class SeedListSource:
    """Source that yields variants from a fixed list of seed strings."""

    def __init__(self, seeds: Sequence[str | tuple[str | None, str]]):
        self._seeds: list[tuple[str | None, str]] = []
        for seed in seeds:
            if isinstance(seed, tuple):
                self._seeds.append(seed)
            else:
                self._seeds.append((None, seed))
        self._i = 0
        self._base = None

    def name(self) -> str:
        return "seed-list"

    def seed(self, base: SourceSpec) -> None:
        self._base = base

    def next_batch(self, n: int) -> list[SourceVariant]:
        out = []
        while self._i < len(self._seeds) and len(out) < n:
            candidate_id, txt = self._seeds[self._i]
            self._i += 1
            mutation = candidate_id or f"seed#{self._i}"
            meta = (
                {"candidate_id_override": candidate_id}
                if candidate_id else {}
            )
            out.append(
                SourceVariant(
                    txt,
                    Provenance("seed-list", None, mutation, "base", meta),
                )
            )
        return out

    def observe(self, scored) -> None:
        pass
