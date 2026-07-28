"""Memory-bounded memo storage for exact x86 semantic analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


READABLE_GLOBAL_EFFECT_SEMANTICS = "readable-global-effect-v1"

DependencyRows = tuple[tuple[str, int, str], ...]


@dataclass(frozen=True, slots=True)
class DependencyMemoEntry:
    """One memo result bound to its exact analysis dependencies."""

    image_sha256: str
    dependencies: DependencyRows
    result: Any


@dataclass(frozen=True, slots=True)
class ReadableGlobalEffectKey:
    """Canonical semantic identity of one readable-global call summary."""

    call_target: int
    slot: int
    field_path: tuple[int, ...]
    exact_call_contexts: tuple[tuple[int, int, int], ...]
    summary_fact_signature: tuple[int, ...]
    control_flow_revision: int
    analysis_semantics: str = READABLE_GLOBAL_EFFECT_SEMANTICS


class ReadableGlobalEffectMemoStore(Protocol):
    """Storage boundary used by readable-global semantic summaries."""

    def get(
        self,
        key: ReadableGlobalEffectKey,
    ) -> DependencyMemoEntry | None: ...

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None: ...

    def __len__(self) -> int: ...

    def close(self) -> None: ...


class InMemoryReadableGlobalEffectMemoStore:
    """Dictionary memo with canonical shared dependency tuples."""

    def __init__(self) -> None:
        self.entries: dict[
            ReadableGlobalEffectKey,
            DependencyMemoEntry,
        ] = {}
        self.dependency_pool: dict[DependencyRows, DependencyRows] = {}

    def _intern_entry(
        self,
        entry: DependencyMemoEntry,
    ) -> DependencyMemoEntry:
        dependencies = self.dependency_pool.setdefault(
            entry.dependencies,
            entry.dependencies,
        )
        if dependencies is entry.dependencies:
            return entry
        return DependencyMemoEntry(
            image_sha256=entry.image_sha256,
            dependencies=dependencies,
            result=entry.result,
        )

    def get(
        self,
        key: ReadableGlobalEffectKey,
    ) -> DependencyMemoEntry | None:
        return self.entries.get(key)

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None:
        self.entries[key] = self._intern_entry(entry)

    def __len__(self) -> int:
        return len(self.entries)

    def close(self) -> None:
        """Release no resources; provided for store-interface symmetry."""
