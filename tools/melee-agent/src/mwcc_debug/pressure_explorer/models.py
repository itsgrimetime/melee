from __future__ import annotations

import pathlib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


def _json_value(value: Any) -> Any:
    if isinstance(value, pathlib.Path):
        return str(value)
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
    source: str = "force-phys"


@dataclass(frozen=True)
class TargetSet:
    function: str | None = None
    targets: tuple[TargetAllocation, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def protected_ig_ids_by_class(self) -> dict[int, set[int]]:
        protected: dict[int, set[int]] = {}
        for target in self.targets:
            protected.setdefault(target.class_id, set()).add(target.ig_id)
        return protected

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class CandidateSpec:
    label: str
    path: str
    kind: str


@dataclass(frozen=True)
class CandidateComparison:
    label: str
    path: str
    status: str
    target_results: dict[str, dict[str, Any]]
    pressure_delta: dict[str, Any]
    identity_status: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FunctionFreshness:
    status: str
    pcdump_mtime: float | None = None
    source_mtime: float | None = None


@dataclass(frozen=True)
class FunctionFacts:
    name: str
    source_path: str | None
    freshness: FunctionFreshness


@dataclass(frozen=True)
class FirstDefSite:
    pass_id: str | None = None
    block_id: str | int | None = None
    instruction_id: str | int | None = None
    opcode: str | None = None
    operands: str | None = None
    normalized: str | None = None


@dataclass(frozen=True)
class SourceAttributionFact:
    status: str
    symbol: str | None = None
    expression: str | None = None
    kind: str | None = None
    source_file: str | None = None
    line: int | None = None
    column: int | None = None
    confidence: str = "unavailable"
    scope: str | None = None
    compiler_temp: bool = False


@dataclass(frozen=True)
class LiveFacts:
    blocks: tuple[str | int, ...] = ()
    intervals: tuple[tuple[int, int], ...] = ()
    confidence: str = "observed"


@dataclass(frozen=True)
class CoalesceFacts:
    root_ig_id: int | None = None
    aliases: tuple[int, ...] = ()


@dataclass(frozen=True)
class SpillFacts:
    spilled: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class AllocatorNode:
    ig_id: int
    virtual_kind: str
    virtual_number: int
    color_status: str
    coalesced_into: int | None
    color_decision_ref: str | None
    first_def: FirstDefSite | None
    source_attribution: SourceAttributionFact
    live: LiveFacts
    degree: int
    flags: tuple[str, ...]
    coalesce: CoalesceFacts
    simplify_order: int | None
    select_order: int | None
    assigned_phys: int | None
    spill: SpillFacts


@dataclass(frozen=True)
class InterferenceEdge:
    a: int
    b: int
    kind: str = "interference"
    confidence: str = "observed"


@dataclass(frozen=True)
class RegisterFacts:
    physical_count: int
    allocatable: tuple[int, ...] = ()
    initial_volatile: tuple[int, ...] = ()
    nonvolatile_dispense_order: tuple[int, ...] = ()
    reserved: tuple[int, ...] = ()
    fixed: tuple[dict[str, Any], ...] = ()
    precolored: tuple[dict[str, Any], ...] = ()
    model_boundary: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class BlockedBy:
    ig_id: int | None = None
    phys: int | None = None


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
    chosen_source: str
    decision_rule: str
    tie_rule: str
    confidence: str
    provenance: str | None = None
    blocked_by: tuple[BlockedBy, ...] = ()
    node_state_before_select: dict[str, Any] = field(default_factory=dict)
    volatile_pool_before: tuple[int, ...] = ()
    nonvolatile_pool_before: dict[str, tuple[int, ...]] = field(default_factory=dict)
    reserved_or_precolored_filtered: tuple[int, ...] = ()


@dataclass(frozen=True)
class AllocatorClassFacts:
    class_id: int
    class_name: str
    registers: RegisterFacts
    nodes: tuple[AllocatorNode, ...] = ()
    edges: tuple[InterferenceEdge, ...] = ()
    coalesce: dict[str, Any] = field(default_factory=dict)
    coalesce_mappings: tuple[tuple[int, int], ...] = ()
    simplify_order: tuple[int, ...] = ()
    select_order: tuple[int, ...] = ()
    color_decisions: tuple[ColorDecision, ...] = ()
    non_allocatable_state: dict[str, Any] = field(default_factory=dict)

    def node_by_ig(self) -> dict[int, AllocatorNode]:
        return {node.ig_id: node for node in self.nodes}

    def decision_by_ig(self) -> dict[int, ColorDecision]:
        return {decision.ig_id: decision for decision in self.color_decisions}


@dataclass(frozen=True)
class AllocatorFacts:
    schema_version: str
    producer: dict[str, Any]
    function: FunctionFacts
    classes: tuple[AllocatorClassFacts, ...] = ()
    adapter_specific: dict[str, Any] = field(default_factory=dict)

    def class_by_id(self) -> dict[int, AllocatorClassFacts]:
        return {allocator_class.class_id: allocator_class for allocator_class in self.classes}

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class Blocker:
    target_ig_id: int
    ig_id: int | None
    kind: str
    assigned_phys: int | None
    impact: int
    reason: str
    source_summary: str | None = None
    confidence: str = "observed"
    target_class: int | None = None


@dataclass(frozen=True)
class TargetPressureReport:
    class_id: int
    ig_id: int
    virtual: dict[str, Any]
    current_phys: int | None
    expected_phys: int | None
    status: str
    first_def: FirstDefSite | None
    source_attribution: SourceAttributionFact | None
    live: LiveFacts | None
    simplify_order: int | None
    select_order: int | None
    coalesce: CoalesceFacts | None
    spill: SpillFacts | None
    blockers: tuple[Blocker, ...]
    why_current_color: str
    must_change: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class ValidationCommand:
    id: str
    purpose: str
    command: str
    mode: str = "emit"
    confidence: str = "exact"


@dataclass(frozen=True)
class SourceHypothesis:
    id: str
    target_ig_id: int
    rank: int
    action: str
    allocator_requirement: str
    source_owner: str
    confidence: str
    status: str = "unvalidated"
    validation_command_ids: tuple[str, ...] = ()
    line_mapping_status: str = "fresh"
    target_class: int | None = None


@dataclass(frozen=True)
class LifetimePressureReport:
    schema_version: str
    function: str
    inventory_only: bool
    inputs: dict[str, Any]
    targets: tuple[TargetPressureReport, ...]
    allocator_facts: AllocatorFacts
    blockers: tuple[Blocker, ...]
    source_attribution: dict[str, Any]
    hypotheses: tuple[SourceHypothesis, ...]
    validation_commands: tuple[ValidationCommand, ...]
    candidate_comparisons: tuple[Any, ...] = ()
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


__all__ = [
    "_json_value",
    "TargetAllocation",
    "TargetSet",
    "CandidateSpec",
    "CandidateComparison",
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
    "Blocker",
    "TargetPressureReport",
    "ValidationCommand",
    "SourceHypothesis",
    "LifetimePressureReport",
]
