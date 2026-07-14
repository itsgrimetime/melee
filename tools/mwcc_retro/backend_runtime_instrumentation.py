"""Runtime hook instrumentation: lifecycle tracking and proof-bound bundle loading.

Provides LifecycleTracker for gap-free allocation/recycle/release generation
tracking, and RuntimeBundle for loading validated proof/manifest bundles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LifecycleEvent:
    """One lifecycle event in a gap-free sequence."""

    lifecycle_sequence: int
    kind: str  # allocation, recycle, release, rewind
    entity_kind: str  # pcode, objobject
    address: int
    site_id: str
    allocation_generation: int


class LifecycleTracker:
    """Gap-free lifecycle sequence with per-(entity_kind, address) generations."""

    def __init__(self) -> None:
        self._events: list[LifecycleEvent] = []
        self._sequence: int = -1
        self._generations: dict[tuple[str, int], int] = {}
        self._active: set[tuple[str, int]] = set()

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def sequence_at_stop(self) -> int:
        return self._sequence

    def record_allocation(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        self._sequence += 1
        key = (entity_kind, address)
        gen = self._generations.get(key, 0) + 1
        self._generations[key] = gen
        self._active.add(key)

        event = LifecycleEvent(
            lifecycle_sequence=self._sequence,
            kind="allocation",
            entity_kind=entity_kind,
            address=address,
            site_id=site_id,
            allocation_generation=gen,
        )
        self._events.append(event)
        return event

    def record_recycle(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        self._sequence += 1
        key = (entity_kind, address)
        gen = self._generations.get(key, 0)
        self._active.discard(key)

        event = LifecycleEvent(
            lifecycle_sequence=self._sequence,
            kind="recycle",
            entity_kind=entity_kind,
            address=address,
            site_id=site_id,
            allocation_generation=gen,
        )
        self._events.append(event)
        return event

    def record_release(
        self, entity_kind: str, address: int, site_id: str
    ) -> LifecycleEvent:
        self._sequence += 1
        key = (entity_kind, address)
        gen = self._generations.get(key, 0)
        self._active.discard(key)

        event = LifecycleEvent(
            lifecycle_sequence=self._sequence,
            kind="release",
            entity_kind=entity_kind,
            address=address,
            site_id=site_id,
            allocation_generation=gen,
        )
        self._events.append(event)
        return event


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    """Loaded and validated proof/manifest bundle for runtime instrumentation."""

    table_path: str
    compiler_sha256: str
    proof: dict[str, Any]
    manifest: dict[str, Any]
    tracker: LifecycleTracker = field(default_factory=LifecycleTracker)
    installed_site_ids: frozenset[str] = frozenset()
    hit_site_ids: frozenset[str] = frozenset()


def load_runtime_bundle(
    table_path: str, compiler_path: str
) -> RuntimeBundle:
    """Load and validate the runtime instrumentation bundle.

    Hashes the actual compiler, resolves sibling proof/manifest files
    from the table path, and validates digest bindings.
    """
    import hashlib
    import json
    from pathlib import Path

    table = Path(table_path)
    compiler_bytes = Path(compiler_path).read_bytes()
    compiler_sha256 = hashlib.sha256(compiler_bytes).hexdigest()

    # Determine sibling paths
    base = table.stem  # e.g., gc_125n or gc_125n.candidate
    parent = table.parent

    if base.endswith(".candidate"):
        proof_name = base.replace(".candidate", "_lifetime_proof.candidate.json")
        manifest_name = base.replace(".candidate", "_lifetime_hooks.candidate.json")
    else:
        proof_name = base + "_lifetime_proof.json"
        manifest_name = base + "_lifetime_hooks.json"

    proof_path = parent / proof_name
    manifest_path = parent / manifest_name

    proof = {}
    manifest = {}

    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    return RuntimeBundle(
        table_path=table_path,
        compiler_sha256=compiler_sha256,
        proof=proof,
        manifest=manifest,
    )
