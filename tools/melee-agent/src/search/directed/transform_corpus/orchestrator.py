"""Probe generation: fan out anchors across families into TransformProbes."""
from __future__ import annotations

import re
from collections.abc import Iterable as IterableABC
from src.mwcc_debug.scheduler_order_realizer import SchedulerOrderTarget, iter_scheduler_order_source_anchors, parse_scheduler_order_target
from src.search.directed.anchors import Anchor, iter_source_shape_anchors
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus.common import _normalize_type_name, _source_file_for_unit, _split_top_level_csv, _target_function_body
from src.search.directed.transform_corpus.contract_signature import _iter_unused_trailing_parameter_anchors
from src.search.directed.transform_corpus.float_literal import _iter_global_float_literal_anchors
from src.search.directed.transform_corpus.fp_reassoc import _iter_fp_subtraction_reassociation_anchors
from src.search.directed.transform_corpus.helper_extract import _iter_helper_shape_anchors
from src.search.directed.transform_corpus.indexed_byte_address import _iter_indexed_byte_address_temp_anchors
from src.search.directed.transform_corpus.local_reuse import _iter_same_type_local_lifetime_reuse_anchors
from src.search.directed.transform_corpus.models import TransformExperimentPlan, TransformProbe
from src.search.directed.transform_corpus.named_zero_local import _iter_named_zero_local_anchors
from src.search.directed.transform_corpus.parameter_area import _iter_outgoing_parameter_area_shape_anchors
from src.search.directed.transform_corpus.pointer_alias import _iter_global_pointer_alias_anchors
from src.search.directed.transform_corpus.pragma_codegen import _iter_function_codegen_pragma_anchors
from src.search.directed.transform_corpus.ranked_cursor_iv import _iter_ranked_cursor_iv_unification_anchors
from src.search.directed.transform_corpus.register_steering import _iter_concrete_register_steering_body_anchors, _iter_node_set_delta_steering_probes, _iter_register_steering_body_anchors
from src.search.directed.transform_corpus.registry import _FAMILY_BY_ID, _FAMILY_IDS_BY_MUTATOR, plan_transform_experiments
from src.search.directed.transform_corpus.return_tail_call import _iter_return_tail_call_anchors
from src.search.directed.transform_corpus.statement_order import _iter_independent_statement_order_anchors
from src.search.directed.transform_corpus.string_data_field import _iter_string_data_field_anchors
from src.search.directed.transform_corpus.struct_field_access import _iter_data_table_indirection_anchors, _iter_raw_index_struct_field_anchors, _iter_raw_pointer_offset_anchors
from src.search.directed.transform_corpus.type_cast import _iter_type_cast_compatibility_anchors
from typing import Any, Mapping


_REGISTER_STEERING_ALIASES = {
    "reorder_local_decls": "steer_reorder_local_decls",
    "split_decl_init": "steer_split_decl_init",
    "reuse_loop_counter_scope": "steer_reuse_loop_counter_scope",
    "change_counter_width": "steer_change_counter_width",
    "reuse_same_type_local_lifetime": "steer_reuse_same_type_local_lifetime",
}


_DIRECT_REGISTER_STEERING_KEYS = frozenset({
    "steer_rotate_local_decl_window",
    "steer_demote_local_decl_to_first_use",
    "steer_reuse_dead_top_level_loop_counter",
    "steer_split_reused_loop_counter",
    "steer_widen_byte_local_type",
    "steer_fpr_dependent_product_recompute",
    "steer_fpr_dependent_product_reuse_temp",
    "steer_fpr_dependent_local_temp_split",
    "steer_fpr_product_assignment_order",
    "steer_fpr_product_cast_temp_split",
    "steer_fpr_product_argument_duplicate",
    "steer_fpr_product_temp_split",
    "steer_fpr_paired_product_temp_split",
    "steer_fpr_product_temp_plus_dependent",
    "steer_fpr_case_c_temp_order",
})


def _region_for_family(plan: TransformExperimentPlan, family_id: str) -> tuple[str, tuple[str, ...]]:
    for cluster in plan.clusters:
        if family_id in cluster.family_ids:
            return "; ".join(cluster.source_regions), cluster.target_assignments
    return "unclustered source region", ()


def _family_ids_for_anchor(anchor: Anchor) -> tuple[str, ...]:
    base_key = anchor.mutator_key.split("@", 1)[0]
    return _FAMILY_IDS_BY_MUTATOR.get(base_key, ())


def _requested_family_ids(families: IterableABC[str] | None) -> tuple[str, ...]:
    if families is None:
        return ()
    requested: list[str] = []
    for family in families:
        if family not in _FAMILY_BY_ID:
            raise ValueError(f"unknown transform family: {family}")
        requested.append(family)
    return tuple(dict.fromkeys(requested))


_ZERO_RETURN_TYPE_RE = re.compile(
    r"\b(?:bool|BOOL|s8|s16|s32|s64|u8|u16|u32|u64|int|short|long)\b"
)


_RETURN_TYPE_QUALIFIER_RE = re.compile(
    r"\b(?:static|inline|extern|const|volatile|register)\b"
)


def _allows_explicit_zero_return(source_text: str, function: str) -> bool:
    target = _target_function_body(source_text, function)
    if target is None:
        return False
    span, _body_text = target
    header = source_text[span.sig_start:span.body_open]
    name_index = header.rfind(function)
    if name_index < 0:
        return False
    return_type = _RETURN_TYPE_QUALIFIER_RE.sub(" ", header[:name_index])
    if "*" in return_type or re.search(r"\bvoid\b", return_type):
        return False
    return _ZERO_RETURN_TYPE_RE.search(return_type) is not None


def _function_lookup_names(
    function: str,
    function_aliases: IterableABC[str] | None,
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for name in (function, *(function_aliases or ())):
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return tuple(names)


def _resolve_target_function(
    source_text: str,
    *,
    function: str,
    function_aliases: IterableABC[str] | None,
):
    for candidate in _function_lookup_names(function, function_aliases):
        target = _target_function_body(source_text, candidate)
        if target is not None:
            return candidate, target
    return None


def _scheduler_order_target_assignments(
    target: SchedulerOrderTarget,
) -> tuple[str, ...]:
    by_label = {
        "target_first": target.target_first,
        "target_second": target.target_second,
    }
    desired_first, desired_second = target.desired_order
    return (f"{by_label[desired_first].opcode} before {by_label[desired_second].opcode}",)


def _prototype_param_type(param: str) -> str | None:
    param = param.strip()
    if not param or param == "void" or "*" in param:
        return None
    parts = param.split()
    if len(parts) < 2:
        return None
    return _normalize_type_name(" ".join(parts[:-1]))


def _source_local_callee_arg_type(
    source_text: str,
    callee: str,
    arg_index: int,
) -> str | None:
    pattern = re.compile(
        r"(?m)^[ \t]*(?:static\s+|extern\s+)?[A-Za-z_]\w*(?:\s+\*?)?\s+"
        + re.escape(callee)
        + r"\s*\((?P<params>[^()]*)\)\s*(?:;|{)"
    )
    for match in pattern.finditer(source_text):
        params = _split_top_level_csv(match.group("params"))
        if params is None or arg_index >= len(params):
            continue
        param_type = _prototype_param_type(params[arg_index])
        if param_type is not None:
            return param_type
    return None


def _body_anchor_allowed(anchor: Anchor, source_text: str, unit: str) -> bool:
    base_key = anchor.mutator_key.split("@", 1)[0]
    if base_key == "elide_numeric_cast":
        cast_type = _normalize_type_name(str(anchor.payload.get("cast_type", "")))
        arg_type = _source_local_callee_arg_type(
            source_text,
            str(anchor.payload.get("callee", "")),
            int(anchor.payload.get("arg_index", -1)),
        )
        return arg_type == cast_type
    if base_key == "collapse_hsd_assert":
        expected_file = _source_file_for_unit(unit).rsplit("/", 1)[-1]
        return anchor.payload.get("file_name") == expected_file
    return True


def _iter_full_source_anchors(source_text: str, *, function: str):
    target = _target_function_body(source_text, function)
    if target is None:
        return
    span, _body_text = target
    yield from _iter_helper_shape_anchors(source_text, function, span)
    yield from _iter_same_type_local_lifetime_reuse_anchors(source_text, span)
    yield from _iter_function_codegen_pragma_anchors(source_text, function, span)
    yield from _iter_return_tail_call_anchors(source_text, function, span)
    yield from _iter_string_data_field_anchors(source_text, function)
    yield from _iter_global_float_literal_anchors(source_text, function, span)
    yield from _iter_fp_subtraction_reassociation_anchors(source_text, function, span)
    yield from _iter_named_zero_local_anchors(source_text, function, span)
    yield from _iter_global_pointer_alias_anchors(source_text, function, span)
    yield from _iter_raw_pointer_offset_anchors(source_text, span)
    yield from _iter_raw_index_struct_field_anchors(source_text, span)
    yield from _iter_data_table_indirection_anchors(source_text, span)
    yield from _iter_type_cast_compatibility_anchors(source_text, function, span)
    yield from _iter_unused_trailing_parameter_anchors(source_text, function, span)
    yield from _iter_outgoing_parameter_area_shape_anchors(
        source_text,
        function,
        span,
    )
    yield from _iter_indexed_byte_address_temp_anchors(source_text, function, span)
    yield from _iter_independent_statement_order_anchors(source_text, span)
    yield from _iter_ranked_cursor_iv_unification_anchors(source_text, function, span)


def _iter_target_function_anchors(source_text: str, function: str):
    target = _target_function_body(source_text, function)
    if target is None:
        return
    span, body_text = target
    body_start = span.body_open
    allow_explicit_zero_return = _allows_explicit_zero_return(source_text, function)
    for anchor in iter_source_shape_anchors(body_text):
        if anchor.mutator_key == "add_explicit_zero_return" and not allow_explicit_zero_return:
            continue
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
    function_aliases: IterableABC[str] | None = None,
    families: IterableABC[str] | None = None,
    max_per_family: int = 3,
    node_set_delta: Mapping[str, Any] | None = None,
    scheduler_order_target: Mapping[str, Any] | SchedulerOrderTarget | str | None = None,
) -> tuple[TransformProbe, ...]:
    """Instantiate applicable corpus families into source probe candidates."""

    plan = plan_transform_experiments(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    requested_family_ids = _requested_family_ids(families)
    allowed = {family.family_id for family in plan.families}
    allowed.update(requested_family_ids)
    if node_set_delta is not None:
        allowed.add("coloring_register_steering")
    parsed_scheduler_target: SchedulerOrderTarget | None = None
    if scheduler_order_target is not None:
        parsed_scheduler_target = (
            scheduler_order_target
            if isinstance(scheduler_order_target, SchedulerOrderTarget)
            else parse_scheduler_order_target(scheduler_order_target)
        )
        allowed.add("scheduler_order_source_realizer")
        if not force_phys and not requested_family_ids and node_set_delta is None:
            allowed = {"scheduler_order_source_realizer"}
    resolved_target = _resolve_target_function(
        source_text,
        function=function,
        function_aliases=function_aliases,
    )
    if resolved_target is None:
        return ()
    source_function, target = resolved_target
    function_span, body_text = target
    body_start = function_span.body_open
    body_end = function_span.full_end
    function_header_text = source_text[function_span.sig_start:function_span.body_open]
    allow_explicit_zero_return = _allows_explicit_zero_return(
        source_text,
        source_function,
    )
    counts: dict[str, int] = {}
    probes: list[TransformProbe] = []
    seen_candidate_texts: set[str] = set()

    def append_probe(
        *,
        family_id: str,
        anchor: Anchor,
        candidate_text: str,
        target_assignments_override: tuple[str, ...] | None = None,
    ) -> None:
        if candidate_text in seen_candidate_texts:
            return
        seen_candidate_texts.add(candidate_text)
        family = _FAMILY_BY_ID[family_id]
        region, target_assignments = _region_for_family(plan, family_id)
        if target_assignments_override is not None:
            target_assignments = target_assignments_override
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

    def append_steering_probe_from_body_anchor(local_anchor: Anchor) -> None:
        if "coloring_register_steering" not in allowed:
            return
        if counts.get("coloring_register_steering", 0) >= max_per_family:
            return
        alias_key = _REGISTER_STEERING_ALIASES.get(local_anchor.mutator_key)
        if alias_key is None and local_anchor.mutator_key in _DIRECT_REGISTER_STEERING_KEYS:
            alias_key = local_anchor.mutator_key
        if alias_key is None:
            return
        start, end = local_anchor.span
        alias_local_anchor = Anchor(
            mutator_key=alias_key,
            span=local_anchor.span,
            payload=local_anchor.payload,
        )
        candidate_body = apply_mutator(alias_key, alias_local_anchor, body_text)
        if candidate_body is None or candidate_body == body_text:
            return
        alias_anchor = Anchor(
            mutator_key=alias_key,
            span=(body_start + start, body_start + end),
            payload=local_anchor.payload,
        )
        append_probe(
            family_id="coloring_register_steering",
            anchor=alias_anchor,
            candidate_text=source_text[:body_start] + candidate_body + source_text[body_end:],
        )

    def append_steering_probe_from_source_anchor(anchor: Anchor) -> None:
        if "coloring_register_steering" not in allowed:
            return
        if counts.get("coloring_register_steering", 0) >= max_per_family:
            return
        alias_key = _REGISTER_STEERING_ALIASES.get(anchor.mutator_key)
        if alias_key is None and anchor.mutator_key in _DIRECT_REGISTER_STEERING_KEYS:
            alias_key = anchor.mutator_key
        if alias_key is None:
            return
        alias_anchor = Anchor(
            mutator_key=alias_key,
            span=anchor.span,
            payload=anchor.payload,
        )
        candidate_text = apply_mutator(alias_key, alias_anchor, source_text)
        if candidate_text is None or candidate_text == source_text:
            return
        append_probe(
            family_id="coloring_register_steering",
            anchor=alias_anchor,
            candidate_text=candidate_text,
        )

    if node_set_delta is not None and "coloring_register_steering" in allowed:
        remaining = max_per_family - counts.get("coloring_register_steering", 0)
        for anchor, candidate_text, target_assignments in (
            _iter_node_set_delta_steering_probes(
                source_text,
                function=source_function,
                node_set_delta=node_set_delta,
                remaining=remaining,
            )
        ):
            append_probe(
                family_id="coloring_register_steering",
                anchor=anchor,
                candidate_text=candidate_text,
                target_assignments_override=target_assignments,
            )

    if (
        parsed_scheduler_target is not None
        and "scheduler_order_source_realizer" in allowed
    ):
        remaining = max_per_family - counts.get("scheduler_order_source_realizer", 0)
        target_assignments = _scheduler_order_target_assignments(
            parsed_scheduler_target,
        )
        for anchor in iter_scheduler_order_source_anchors(
            source_text,
            function=source_function,
            target=parsed_scheduler_target,
            remaining=remaining,
        ):
            if counts.get("scheduler_order_source_realizer", 0) >= max_per_family:
                break
            candidate_text = apply_mutator(anchor.mutator_key, anchor, source_text)
            if candidate_text is None or candidate_text == source_text:
                continue
            append_probe(
                family_id="scheduler_order_source_realizer",
                anchor=anchor,
                candidate_text=candidate_text,
                target_assignments_override=target_assignments,
            )

    for local_anchor in _iter_concrete_register_steering_body_anchors(
        body_text,
        function_header_text=function_header_text,
    ):
        append_steering_probe_from_body_anchor(local_anchor)
    for local_anchor in iter_source_shape_anchors(body_text):
        if (
            local_anchor.mutator_key == "add_explicit_zero_return"
            and not allow_explicit_zero_return
        ):
            continue
        if not _body_anchor_allowed(local_anchor, source_text, unit):
            continue
        start, end = local_anchor.span
        anchor = Anchor(
            mutator_key=local_anchor.mutator_key,
            span=(body_start + start, body_start + end),
            payload=local_anchor.payload,
        )
        append_steering_probe_from_body_anchor(local_anchor)
        for family_id in _family_ids_for_anchor(anchor):
            if family_id not in allowed:
                continue
            if counts.get(family_id, 0) >= max_per_family:
                continue
            candidate_body = apply_mutator(
                local_anchor.mutator_key,
                local_anchor,
                body_text,
            )
            if candidate_body is None or candidate_body == body_text:
                continue
            candidate_text = (
                source_text[:body_start] + candidate_body + source_text[body_end:]
            )
            append_probe(
                family_id=family_id,
                anchor=anchor,
                candidate_text=candidate_text,
            )
    for local_anchor in _iter_register_steering_body_anchors(body_text):
        append_steering_probe_from_body_anchor(local_anchor)
    for anchor in _iter_full_source_anchors(source_text, function=source_function):
        append_steering_probe_from_source_anchor(anchor)
        for family_id in _family_ids_for_anchor(anchor):
            if family_id not in allowed:
                continue
            if counts.get(family_id, 0) >= max_per_family:
                continue
            candidate_text = apply_mutator(anchor.mutator_key, anchor, source_text)
            if candidate_text is None or candidate_text == source_text:
                continue
            append_probe(
                family_id=family_id,
                anchor=anchor,
                candidate_text=candidate_text,
            )
    return tuple(probes)
