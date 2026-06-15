"""Public dataclasses for the source-transform corpus."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransformFamily:
    """Reusable source-transform family metadata."""

    family_id: str
    label: str
    mutator_keys: tuple[str, ...]
    semantic_risk: str
    source_region_selector: str
    expected_compiler_effect: str
    generated_probe_form: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransformCluster:
    """A diagnostic source-region cluster that should be probed together."""

    cluster_id: str
    label: str
    source_regions: tuple[str, ...]
    target_assignments: tuple[str, ...]
    family_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class TransformExperimentPlan:
    """Static plan that maps a proof vector to transform families."""

    function: str
    unit: str
    source_file: str
    clusters: tuple[TransformCluster, ...]
    families: tuple[TransformFamily, ...]


@dataclass(frozen=True)
class TransformProbe:
    """A materialized source probe produced from an anchor and family."""

    probe_id: str
    family_id: str
    family_label: str
    mutator_key: str
    semantic_risk: str
    source_region: str
    expected_compiler_effect: str
    generated_probe_form: str
    target_assignments: tuple[str, ...]
    span: tuple[int, int]
    payload: dict
    candidate_text: str
