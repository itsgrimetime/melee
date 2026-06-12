"""Source-transform corpus and bounded probe planner for directed search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from src.search.directed.anchors import Anchor, iter_source_shape_anchors
from src.search.directed.mutators import apply_mutator
from src.mwcc_debug.symbol_bridge import _extract_function_text


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


DEFAULT_TRANSFORM_FAMILIES: tuple[TransformFamily, ...] = (
    TransformFamily(
        family_id="temp_sink_hoist",
        label="temp sink/hoist",
        mutator_keys=("widen_local_lifetime", "narrow_local_lifetime"),
        semantic_risk="low",
        source_region_selector="local temporary declarations near reload/call boundaries",
        expected_compiler_effect="change temp live-range overlap and allocator pressure",
        generated_probe_form="move a local declaration across a nearby control boundary",
        keywords=("temp", "sink", "hoist", "reload"),
    ),
    TransformFamily(
        family_id="condition_split_merge",
        label="condition split/merge",
        mutator_keys=("flatten_nested_if", "unflatten_else_if"),
        semantic_risk="low",
        source_region_selector="adjacent if/else-if predicate blocks",
        expected_compiler_effect="change predicate-temp and branch-reload lifetimes",
        generated_probe_form="toggle nested else-if and explicit else { if (...) } forms",
        keywords=("condition", "predicate", "split", "merge"),
    ),
    TransformFamily(
        family_id="scoped_alias",
        label="scoped alias",
        mutator_keys=("split_decl_init",),
        semantic_risk="medium",
        source_region_selector="single local declaration with initializer",
        expected_compiler_effect="introduce a source-visible alias/use boundary",
        generated_probe_form="split declaration initializers before later use-site rewrites",
        keywords=("alias", "scope", "initializer"),
    ),
    TransformFamily(
        family_id="declaration_use_boundary",
        label="declaration/use boundary movement",
        mutator_keys=("reorder_local_decls", "split_decl_init"),
        semantic_risk="low",
        source_region_selector="adjacent local declarations and declaration initializers",
        expected_compiler_effect="change declaration-order and first-use tie-breaks",
        generated_probe_form="swap adjacent declarations or split declaration initializers",
        keywords=("decl", "order", "boundary", "use"),
    ),
    TransformFamily(
        family_id="loop_index_pointer_walk_split",
        label="loop index vs pointer-walk role split",
        mutator_keys=("reuse_loop_counter_scope",),
        semantic_risk="medium",
        source_region_selector="nested loop counter declarations",
        expected_compiler_effect="change loop-index and pointer-walk holder overlap",
        generated_probe_form="reuse an outer loop counter instead of redeclaring an inner one",
        keywords=("loop", "index", "pointer", "walk"),
    ),
    TransformFamily(
        family_id="helper_shape",
        label="helper inline/extract and argument shape",
        mutator_keys=(),
        semantic_risk="high",
        source_region_selector="helper call and candidate inline boundaries",
        expected_compiler_effect="change call-adjacent temp materialization",
        generated_probe_form="record-only family until helper extraction mutators exist",
        keywords=("helper", "inline", "extract", "argument"),
    ),
    TransformFamily(
        family_id="counter_type_shape",
        label="int vs s32 loop counter",
        mutator_keys=("change_counter_width",),
        semantic_risk="low",
        source_region_selector="loop counter declarations",
        expected_compiler_effect="change MWCC loop and induction-variable heuristics",
        generated_probe_form="toggle counter width/type where source-compatible",
        keywords=("int", "s32", "loop", "counter"),
    ),
    TransformFamily(
        family_id="reload_branch_scope",
        label="reload branch scope",
        mutator_keys=("add_branch_scope", "remove_branch_scope"),
        semantic_risk="low",
        source_region_selector="branch bodies around reloads and predicate tests",
        expected_compiler_effect="change reload lifetime and branch-local pressure",
        generated_probe_form="add or remove one brace-only branch-local scope",
        keywords=("reload", "branch", "scope"),
    ),
    TransformFamily(
        family_id="lifetime_preserve_shorten",
        label="lifetime preserve/shorten around calls/loops",
        mutator_keys=("widen_local_lifetime", "narrow_local_lifetime"),
        semantic_risk="medium",
        source_region_selector="local declarations near call, loop, or branch boundaries",
        expected_compiler_effect="extend or shorten holder lifetime across allocator pressure points",
        generated_probe_form="move a local declaration outward or inward across a boundary",
        keywords=("lifetime", "preserve", "shorten", "call", "loop"),
    ),
)


_FAMILY_BY_ID = {family.family_id: family for family in DEFAULT_TRANSFORM_FAMILIES}
_FAMILY_IDS_BY_MUTATOR: dict[str, tuple[str, ...]] = {}
for _family in DEFAULT_TRANSFORM_FAMILIES:
    for _mutator_key in _family.mutator_keys:
        _FAMILY_IDS_BY_MUTATOR.setdefault(_mutator_key, ())
        _FAMILY_IDS_BY_MUTATOR[_mutator_key] = (
            *_FAMILY_IDS_BY_MUTATOR[_mutator_key],
            _family.family_id,
        )


def _assignment_labels(force_phys: Mapping[int, int]) -> tuple[str, ...]:
    return tuple(f"ig{ig}->r{phys}" for ig, phys in sorted(force_phys.items()))


def _cluster_assignments(
    force_phys: Mapping[int, int],
    virtuals: Iterable[int],
) -> tuple[str, ...]:
    return tuple(
        f"ig{ig}->r{force_phys[ig]}"
        for ig in virtuals
        if ig in force_phys
    )


def _source_file_for_unit(unit: str) -> str:
    return f"src/{unit}.c" if not unit.startswith("src/") else unit


def _families_for_clusters(clusters: tuple[TransformCluster, ...]) -> tuple[TransformFamily, ...]:
    wanted = {family_id for cluster in clusters for family_id in cluster.family_ids}
    return tuple(family for family in DEFAULT_TRANSFORM_FAMILIES if family.family_id in wanted)


def plan_transform_experiments(
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
) -> TransformExperimentPlan:
    """Map a directed diagnostic proof vector to transform-family clusters."""

    if function == "ftCo_8009E7B4" and ({58, 44, 42} & set(force_phys)):
        early = TransformCluster(
            cluster_id="early_flag_reload",
            label="early flag/reload temps",
            source_regions=(
                "early flag/reload block",
                "boolean flag temp and reload boundary",
                "early volatile call-adjacent temps",
            ),
            target_assignments=_cluster_assignments(force_phys, (58, 44, 42)),
            family_ids=(
                "condition_split_merge",
                "reload_branch_scope",
                "declaration_use_boundary",
                "lifetime_preserve_shorten",
            ),
            rationale=(
                "Move the early volatile-register proof holders as one source "
                "shape rather than as isolated virtual nudges."
            ),
        )
        late = TransformCluster(
            cluster_id="late_field_loop_tree",
            label="late x594_b4/x594_b3 loop IV/tree-pointer swaps",
            source_regions=(
                "x594_b4/x594_b3 field-bit tests",
                "loop IV/tree-pointer lifetime boundary",
                "late callee-save holder overlap",
            ),
            target_assignments=_cluster_assignments(force_phys, (35, 56, 34)),
            family_ids=(
                "condition_split_merge",
                "loop_index_pointer_walk_split",
                "reload_branch_scope",
                "lifetime_preserve_shorten",
                "counter_type_shape",
            ),
            rationale=(
                "Probe field-bit predicates together with loop-index and "
                "tree-pointer lifetime changes."
            ),
        )
        clusters = tuple(
            cluster for cluster in (early, late) if cluster.target_assignments
        )
    else:
        clusters = (
            TransformCluster(
                cluster_id="generic_allocator_shape",
                label="generic allocator-shape source cluster",
                source_regions=(
                    "proof-vector source region unresolved",
                    "run diagnose/reanchor to refine source spans",
                ),
                target_assignments=_assignment_labels(force_phys),
                family_ids=(
                    "declaration_use_boundary",
                    "condition_split_merge",
                    "reload_branch_scope",
                    "lifetime_preserve_shorten",
                    "loop_index_pointer_walk_split",
                ),
                rationale="Bounded fallback when the diagnostic lacks a named source cluster.",
            ),
        )

    return TransformExperimentPlan(
        function=function,
        unit=unit,
        source_file=_source_file_for_unit(unit),
        clusters=clusters,
        families=_families_for_clusters(clusters),
    )


def _region_for_family(plan: TransformExperimentPlan, family_id: str) -> tuple[str, tuple[str, ...]]:
    for cluster in plan.clusters:
        if family_id in cluster.family_ids:
            return "; ".join(cluster.source_regions), cluster.target_assignments
    return "unclustered source region", ()


def _family_ids_for_anchor(anchor: Anchor) -> tuple[str, ...]:
    base_key = anchor.mutator_key.split("@", 1)[0]
    return _FAMILY_IDS_BY_MUTATOR.get(base_key, ())


def _iter_target_function_anchors(source_text: str, function: str):
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return
    _params_text, body_text, _start_line = extracted
    body_start = source_text.find(body_text)
    if body_start < 0:
        return
    for anchor in iter_source_shape_anchors(body_text):
        start, end = anchor.span
        yield Anchor(
            mutator_key=anchor.mutator_key,
            span=(body_start + start, body_start + end),
            payload=anchor.payload,
        )


def generate_transform_probes(
    source_text: str,
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
    max_per_family: int = 3,
) -> tuple[TransformProbe, ...]:
    """Instantiate applicable corpus families into source probe candidates."""

    plan = plan_transform_experiments(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    allowed = {family.family_id for family in plan.families}
    counts: dict[str, int] = {}
    probes: list[TransformProbe] = []
    for anchor in _iter_target_function_anchors(source_text, function):
        for family_id in _family_ids_for_anchor(anchor):
            if family_id not in allowed:
                continue
            if counts.get(family_id, 0) >= max_per_family:
                continue
            candidate_text = apply_mutator(anchor.mutator_key, anchor, source_text)
            if candidate_text is None or candidate_text == source_text:
                continue
            family = _FAMILY_BY_ID[family_id]
            region, target_assignments = _region_for_family(plan, family_id)
            ordinal = counts.get(family_id, 0)
            counts[family_id] = ordinal + 1
            probes.append(
                TransformProbe(
                    probe_id=f"{family_id}@{ordinal}",
                    family_id=family_id,
                    family_label=family.label,
                    mutator_key=anchor.mutator_key,
                    semantic_risk=family.semantic_risk,
                    source_region=region,
                    expected_compiler_effect=family.expected_compiler_effect,
                    generated_probe_form=family.generated_probe_form,
                    target_assignments=target_assignments,
                    span=anchor.span,
                    payload=dict(anchor.payload),
                    candidate_text=candidate_text,
                )
            )
    return tuple(probes)
