from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import Any


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_json_value(item) for item in sorted(value, key=str)]
    return value


@dataclass(frozen=True)
class TargetAllocation:
    class_id: int
    ig_id: int
    expected_phys: int
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class TargetSet:
    targets: tuple[TargetAllocation, ...]
    function: str | None = None
    provenance: dict[str, Any] | None = None

    def protected_ig_ids_by_class(self) -> dict[int, set[int]]:
        protected: dict[int, set[int]] = {}
        for target in self.targets:
            protected.setdefault(target.class_id, set()).add(target.ig_id)
        return protected

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class FunctionFreshness:
    function: str
    source_path: str | None = None
    source_mtime_ns: int | None = None
    pcdump_path: str | None = None
    pcdump_mtime_ns: int | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class FirstDefSite:
    class_id: int
    ig_id: int
    block: str | None = None
    instruction_index: int | None = None
    opcode: str | None = None
    source_span: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceAttributionFact:
    class_id: int
    ig_id: int
    source: str | None = None
    confidence: float | None = None
    first_def: FirstDefSite | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveFacts:
    class_id: int
    ig_id: int
    live_range: tuple[int, int] | None = None
    use_count: int | None = None
    first_def: FirstDefSite | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class CoalesceFacts:
    class_id: int
    ig_id: int
    root_ig_id: int | None = None
    aliases: tuple[int, ...] = ()
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class SpillFacts:
    class_id: int
    ig_id: int
    spilled: bool
    spill_slot: int | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class AllocatorNode:
    class_id: int
    ig_id: int
    color_decision_ref: str | None = None
    assigned_phys: int | None = None
    source: SourceAttributionFact | None = None
    live: LiveFacts | None = None
    coalesce: CoalesceFacts | None = None
    spill: SpillFacts | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class InterferenceEdge:
    class_id: int
    left_ig_id: int
    right_ig_id: int
    reason: str | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegisterFacts:
    class_id: int
    available_phys_ordered: tuple[int, ...] = ()
    fixed: tuple[dict[str, Any], ...] = ()
    precolored: tuple[dict[str, Any], ...] = ()
    model_boundary: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class BlockedBy:
    kind: str
    ig_id: int | None = None
    phys: int | None = None
    reason: str | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class BlockedCandidate:
    phys: int
    holder_ig_id: int | None = None
    holder_assigned_phys: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ColorDecision:
    id: str
    ig_id: int
    iter: int
    assigned_phys: int | None
    available_phys_ordered: tuple[int, ...]
    blocked_candidates: tuple[BlockedCandidate, ...]
    candidate_phys_ordered: tuple[int, ...]
    chosen_source: str | None
    decision_rule: str | None
    tie_rule: str | None
    confidence: float | None
    provenance: dict[str, Any] | None = None
    blocked_by: tuple[BlockedBy, ...] = ()
    node_state_before_select: dict[str, Any] | None = None
    volatile_pool_before: tuple[int, ...] = ()
    nonvolatile_pool_before: tuple[int, ...] = ()
    reserved_or_precolored_filtered: tuple[int, ...] = ()


@dataclass(frozen=True)
class AllocatorClassFacts:
    class_id: int
    register_facts: RegisterFacts | None = None
    nodes: tuple[AllocatorNode, ...] = ()
    interference_edges: tuple[InterferenceEdge, ...] = ()
    color_decisions: tuple[ColorDecision, ...] = ()
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class FunctionFacts:
    function: str
    freshness: FunctionFreshness | None = None
    classes: tuple[AllocatorClassFacts, ...] = ()
    targets: TargetSet | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class AllocatorFacts:
    functions: tuple[FunctionFacts, ...] = ()
    targets: TargetSet | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


__all__ = [
    "_json_value",
    "TargetAllocation",
    "TargetSet",
    "FunctionFreshness",
    "FirstDefSite",
    "SourceAttributionFact",
    "LiveFacts",
    "CoalesceFacts",
    "SpillFacts",
    "AllocatorNode",
    "InterferenceEdge",
    "RegisterFacts",
    "BlockedBy",
    "BlockedCandidate",
    "ColorDecision",
    "AllocatorClassFacts",
    "FunctionFacts",
    "AllocatorFacts",
]
