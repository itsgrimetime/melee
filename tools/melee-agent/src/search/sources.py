"""SourceVariant generators for search substrate."""

from __future__ import annotations

from src.search.types import SourceVariant, SourceSpec
from src.search.artifact import Provenance


class SeedListSource:
    """Source that yields variants from a fixed list of seed strings."""

    def __init__(self, seeds: list[str]):
        self._seeds = list(seeds)
        self._i = 0
        self._base = None

    def name(self) -> str:
        return "seed-list"

    def seed(self, base: SourceSpec) -> None:
        self._base = base

    def next_batch(self, n: int) -> list[SourceVariant]:
        out = []
        while self._i < len(self._seeds) and len(out) < n:
            txt = self._seeds[self._i]
            self._i += 1
            out.append(
                SourceVariant(
                    txt,
                    Provenance("seed-list", None, f"seed#{self._i}", "base", {}),
                )
            )
        return out

    def observe(self, scored) -> None:
        pass
