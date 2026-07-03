from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..colorgraph_parser import FunctionEvents, find_function, parse_hook_events
from ..parser import Function, Instruction, parse_pcdump
from ..tiebreak import build_ig, class_section
from ..virtual_attribution import explain_virtuals
from .models import (
    AllocatorClassFacts,
    AllocatorFacts,
    AllocatorNode,
    BlockedBy,
    BlockedCandidate,
    CoalesceFacts,
    ColorDecision,
    FirstDefSite,
    FunctionFacts,
    FunctionFreshness,
    InterferenceEdge,
    LiveFacts,
    RegisterFacts,
    SourceAttributionFact,
    SpillFacts,
)


def facts_from_pcdump(
    pcdump_text: str,
    function: str,
    *,
    pcdump_path: str | Path | None = None,
    source_text: str | None = None,
    source_path: str | Path | None = None,
    class_filter: tuple[int, ...] | None = None,
) -> AllocatorFacts:
    hook_events = parse_hook_events(pcdump_text)
    events = find_function(hook_events, function)
    parsed_functions = parse_pcdump(pcdump_text, function=function)
    parsed_function = parsed_functions[0] if parsed_functions else None
    if events is None:
        raise ValueError(f"{function} not found in pcdump hook events")

    class_ids = class_filter if class_filter is not None else _event_class_ids(events)
    classes = tuple(
        _class_facts_from_pcdump(
            pcdump_text,
            function,
            events,
            parsed_function,
            class_id=class_id,
            source_text=source_text,
            source_path=source_path,
        )
        for class_id in class_ids
    )
    return AllocatorFacts(
        schema_version="allocator-facts.v1",
        producer={"kind": "mwcc-debug-pcdump", "path": _path_str(pcdump_path)},
        function=FunctionFacts(
            name=function,
            source_path=_path_str(source_path),
            freshness=_freshness(pcdump_path, source_path),
        ),
        classes=classes,
    )


def facts_from_backend_trace(path: Path, *, function: str) -> AllocatorFacts:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, Mapping):
        raise ValueError("backend trace missing required allocator facts: root")
    fn_data = _select_backend_function(data, function)
    class_payloads = _backend_class_payloads(fn_data)
    if not isinstance(class_payloads, Sequence) or isinstance(class_payloads, str):
        raise ValueError("backend trace missing required allocator facts: classes")

    classes = tuple(_class_facts_from_backend_trace(cls) for cls in class_payloads)
    return AllocatorFacts(
        schema_version=str(data.get("schema_version", "allocator-facts.v1")),
        producer={
            "kind": "mwcc-retro-backend-trace",
            "path": str(path),
        },
        function=FunctionFacts(
            name=function,
            source_path=_maybe_str(fn_data.get("source_path")),
            freshness=FunctionFreshness(status="unknown"),
        ),
        classes=classes,
        adapter_specific={
            key: value
            for key, value in data.items()
            if key not in {"functions", "schema_version"}
        },
    )


def _class_facts_from_pcdump(
    pcdump_text: str,
    function: str,
    events: FunctionEvents,
    parsed_function: Function | None,
    *,
    class_id: int,
    source_text: str | None,
    source_path: str | Path | None,
) -> AllocatorClassFacts:
    section = class_section(events, class_id)
    ig = build_ig(section) if section is not None else None
    decisions_by_ig = {
        decision.ig_idx: decision
        for decision in (section.decisions if section is not None else ())
    }
    simplify_by_ig = {
        entry.ig_idx: entry
        for simplify in events.simplify_sections
        if simplify.class_id == class_id
        for entry in simplify.entries
        if entry.ig_idx >= 0
    }
    alias_root_phys = {
        alias: (root, root_phys)
        for aliases in events.coalesced_alias_sections
        if aliases.class_id == class_id
        for alias, root, root_phys in aliases.aliases
    }
    coalesce_aliases = {
        alias: root
        for coalesce in events.coalesce_sections
        if coalesce.class_id == class_id
        for alias, root in coalesce.mappings
    }
    alias_to_root = {**coalesce_aliases, **{k: v[0] for k, v in alias_root_phys.items()}}
    root_to_aliases: dict[int, list[int]] = {}
    for alias, root in alias_to_root.items():
        root_to_aliases.setdefault(root, []).append(alias)

    ig_ids = set(decisions_by_ig) | set(simplify_by_ig) | set(alias_to_root)
    ig_ids.update(alias_to_root.values())
    if ig is not None:
        ig_ids.update(ig.nodes)
        for node in ig.nodes.values():
            ig_ids.update(n for n in node.neighbors if n >= 32)

    attribution = _virtual_attribution(
        pcdump_text,
        function,
        class_id=class_id,
        ig_ids=ig_ids,
        source_text=source_text,
        source_path=source_path,
    )
    nodes = tuple(
        _node_from_pcdump(
            ig_id,
            class_id=class_id,
            parsed_function=parsed_function,
            decision=decisions_by_ig.get(ig_id),
            simplify=simplify_by_ig.get(ig_id),
            ig_node=None if ig is None else ig.nodes.get(ig_id),
            attribution=attribution.get(ig_id),
            alias_to_root=alias_to_root,
            alias_root_phys=alias_root_phys,
            root_to_aliases=root_to_aliases,
            decisions_by_ig=decisions_by_ig,
            simplify_by_ig=simplify_by_ig,
        )
        for ig_id in sorted(ig_ids)
    )
    color_decisions = tuple(
        _color_decision_from_pcdump(
            class_id,
            decision,
            decisions_by_ig=decisions_by_ig,
            ig_node=None if ig is None else ig.nodes.get(decision.ig_idx),
        )
        for decision in sorted(decisions_by_ig.values(), key=lambda item: item.iter_idx)
    )
    edges = (
        _edges_from_ig(ig)
        if ig is not None
        else tuple()
    )
    coalesce = _coalesce_payload(events, class_id)
    return AllocatorClassFacts(
        class_id=class_id,
        class_name=_class_name(class_id),
        registers=_register_policy(class_id),
        nodes=nodes,
        edges=edges,
        coalesce=coalesce,
        coalesce_mappings=tuple(
            sorted((alias, root) for alias, root in coalesce_aliases.items())
        ),
        simplify_order=tuple(
            entry.ig_idx
            for entry in sorted(simplify_by_ig.values(), key=lambda item: item.iter_idx)
        ),
        select_order=tuple(() if ig is None else ig.select_order),
        color_decisions=color_decisions,
    )


def _class_facts_from_backend_trace(payload: Any) -> AllocatorClassFacts:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: classes[]")
    _require_fields(
        payload,
        (
            "class_id",
            "class_name",
            "registers",
            "nodes",
            "edges",
            "coalesce",
            "non_allocatable_state",
            "simplify_order",
            "select_order",
            "color_decisions",
        ),
    )
    class_id = int(payload["class_id"])
    nodes = tuple(_node_from_mapping(node) for node in payload["nodes"])
    nodes = _inherit_backend_alias_assignments(nodes, payload)
    return AllocatorClassFacts(
        class_id=class_id,
        class_name=str(payload.get("class_name", _class_name(class_id))),
        registers=_registers_from_mapping(payload["registers"]),
        nodes=nodes,
        edges=tuple(_edge_from_mapping(edge) for edge in payload["edges"]),
        coalesce=dict(payload.get("coalesce", {})),
        coalesce_mappings=tuple(
            _coalesce_mapping_pair(item)
            for item in payload.get("coalesce_mappings", ())
        ),
        simplify_order=tuple(int(item) for item in payload.get("simplify_order", ())),
        select_order=tuple(int(item) for item in payload.get("select_order", ())),
        color_decisions=tuple(
            _decision_from_mapping(decision, index=index)
            for index, decision in enumerate(payload["color_decisions"])
        ),
        non_allocatable_state=dict(payload.get("non_allocatable_state", {})),
    )


def _select_backend_function(data: Mapping[str, Any], function: str) -> Mapping[str, Any]:
    functions = _required(data, "functions")
    if isinstance(functions, Sequence) and not isinstance(functions, str):
        if any(not isinstance(fn, Mapping) for fn in functions):
            raise ValueError("backend trace missing required allocator facts: functions")
        selected = next(
            (
                fn
                for fn in functions
                if fn.get("name") == function
            ),
            None,
        )
    else:
        raise ValueError("backend trace missing required allocator facts: functions")
    if selected is None:
        raise ValueError(f"{function} not found in backend trace")
    if not isinstance(selected, Mapping):
        raise ValueError("backend trace missing required allocator facts: functions.<function>")
    return selected


def _backend_class_payloads(fn_data: Mapping[str, Any]) -> Any:
    regalloc = _required(fn_data, "regalloc")
    if not isinstance(regalloc, Mapping):
        raise ValueError("backend trace missing required allocator facts: regalloc")
    return _required(regalloc, "classes")


def _inherit_backend_alias_assignments(
    nodes: tuple[AllocatorNode, ...],
    class_payload: Mapping[str, Any],
) -> tuple[AllocatorNode, ...]:
    by_ig = {node.ig_id: node for node in nodes}
    root_phys_by_alias = {
        int(mapping["alias"]): _maybe_int(mapping.get("root_phys"))
        for mapping in class_payload.get("coalesce", {}).get("mappings", ())
        if isinstance(mapping, Mapping)
        and "alias" in mapping
        and "root_phys" in mapping
    }
    out: list[AllocatorNode] = []
    for node in nodes:
        if (
            node.color_status == "coalesced_alias"
            and node.assigned_phys is None
            and node.coalesced_into is not None
        ):
            root = by_ig.get(node.coalesced_into)
            inherited = (
                root.assigned_phys
                if root is not None and root.assigned_phys is not None
                else root_phys_by_alias.get(node.ig_id)
            )
            if inherited is not None:
                node = replace(node, assigned_phys=inherited)
        out.append(node)
    return tuple(out)


def _coalesce_mapping_pair(item: Any) -> tuple[int, int]:
    if isinstance(item, Mapping):
        return int(item["alias"]), int(item["root"])
    return int(item[0]), int(item[1])


def _node_from_pcdump(
    ig_id: int,
    *,
    class_id: int,
    parsed_function: Function | None,
    decision: Any,
    simplify: Any,
    ig_node: Any,
    attribution: Any,
    alias_to_root: Mapping[int, int],
    alias_root_phys: Mapping[int, tuple[int, int]],
    root_to_aliases: Mapping[int, list[int]],
    decisions_by_ig: Mapping[int, Any],
    simplify_by_ig: Mapping[int, Any],
) -> AllocatorNode:
    root = alias_to_root.get(ig_id)
    root_decision = decisions_by_ig.get(root) if root is not None else None
    root_phys = alias_root_phys.get(ig_id, (None, None))[1]
    assigned_phys = (
        decision.assigned_reg
        if decision is not None
        else root_decision.assigned_reg
        if root_decision is not None
        else root_phys
    )
    spilled = bool(simplify.spilled) if simplify is not None else False
    status = (
        "coalesced_alias"
        if root is not None and decision is None
        else "spilled"
        if spilled
        else "colored"
        if decision is not None
        else "absent"
    )
    decision_ref = (
        _decision_id(class_id, decision.iter_idx)
        if decision is not None
        else _decision_id(class_id, root_decision.iter_idx)
        if root_decision is not None
        else None
    )
    return AllocatorNode(
        ig_id=ig_id,
        virtual_kind=_class_name(class_id),
        virtual_number=ig_id,
        color_status=status,
        coalesced_into=root,
        color_decision_ref=decision_ref,
        first_def=_first_def_fact(attribution, parsed_function, ig_id, class_id),
        source_attribution=_source_attribution_fact(attribution),
        live=_live_fact(attribution),
        degree=(
            ig_node.array_size
            if ig_node is not None
            else simplify.array_size
            if simplify is not None
            else decision.n_interferers
            if decision is not None
            else 0
        ),
        flags=_node_flags(decision, simplify, ig_node),
        coalesce=CoalesceFacts(
            root_ig_id=root if root is not None else ig_id,
            aliases=tuple(sorted(root_to_aliases.get(ig_id, ()))),
        ),
        simplify_order=None if simplify is None else simplify.iter_idx,
        select_order=None if decision is None else decision.iter_idx,
        assigned_phys=assigned_phys,
        spill=SpillFacts(spilled=spilled, reason="simplifygraph" if spilled else None),
    )


def _color_decision_from_pcdump(
    class_id: int,
    decision: Any,
    *,
    decisions_by_ig: Mapping[int, Any],
    ig_node: Any,
) -> ColorDecision:
    blocked = tuple(
        BlockedCandidate(
            phys=_blocked_phys(interferer, assigned),
            holder_ig_id=interferer if interferer >= 32 else None,
            holder_assigned_phys=assigned if assigned >= 0 else None,
            reason="interference",
        )
        for interferer, assigned in decision.interferers
        if _blocked_phys(interferer, assigned) is not None
    )
    register_policy = _register_policy(class_id)
    return ColorDecision(
        id=_decision_id(class_id, decision.iter_idx),
        ig_id=decision.ig_idx,
        iter=decision.iter_idx,
        assigned_phys=decision.assigned_reg if decision.assigned_reg >= 0 else None,
        available_phys_ordered=register_policy.allocatable,
        blocked_candidates=blocked,
        candidate_phys_ordered=tuple(
            phys
            for phys in register_policy.allocatable
            if phys not in {candidate.phys for candidate in blocked}
        ),
        chosen_source="observed",
        decision_rule="mwcc-colorgraph",
        tie_rule="observed-select-order",
        confidence="observed" if ig_node is not None and not ig_node.incomplete else "synthesized",
        provenance="mwcc-debug-pcdump",
        node_state_before_select={
            "degree": decision.degree,
            "n_interferers": decision.n_interferers,
            "flags": decision.flags,
            "interferers": list(decision.interferers),
            "known_decision_count": len(decisions_by_ig),
        },
    )


def _virtual_attribution(
    pcdump_text: str,
    function: str,
    *,
    class_id: int,
    ig_ids: set[int],
    source_text: str | None,
    source_path: str | Path | None,
) -> dict[int, Any]:
    if not ig_ids:
        return {}
    try:
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=tuple(sorted(ig_ids)),
            source_text=source_text,
            source_file=_path_str(source_path),
            reg_class=_class_name(class_id),
        )
    except ValueError:
        return {}
    out: dict[int, Any] = {}
    for entry in report.virtuals:
        key = entry.ig_idx if entry.ig_idx is not None else entry.virtual
        out[key] = entry
    return out


def _first_def_fact(
    attribution: Any,
    parsed_function: Function | None,
    ig_id: int,
    class_id: int,
) -> FirstDefSite | None:
    site = None
    if attribution is not None and attribution.source is not None:
        site = attribution.source.first_def
    if site is None and attribution is not None:
        site = attribution.first_occurrence
    if site is not None:
        return FirstDefSite(
            pass_id=site.pass_name,
            block_id=site.block_idx,
            instruction_id=site.instr_idx,
            opcode=site.opcode,
            operands=site.operands,
        )
    fallback = _find_first_virtual_instruction(parsed_function, ig_id, class_id)
    if fallback is None:
        return None
    pass_name, block_idx, instr_idx, instruction = fallback
    return FirstDefSite(
        pass_id=pass_name,
        block_id=block_idx,
        instruction_id=instr_idx,
        opcode=instruction.opcode,
        operands=instruction.operands,
    )


def _find_first_virtual_instruction(
    parsed_function: Function | None,
    ig_id: int,
    class_id: int,
) -> tuple[str, int, int, Instruction] | None:
    if parsed_function is None:
        return None
    reg_kind = "f" if class_id == 1 else "r"
    candidate_passes = [parsed_function.last_precolor_pass()]
    candidate_passes.extend(parsed_function.passes)
    seen: set[int] = set()
    for pass_obj in candidate_passes:
        if pass_obj is None or id(pass_obj) in seen:
            continue
        seen.add(id(pass_obj))
        for block in pass_obj.blocks:
            for instr_idx, instruction in enumerate(block.instructions):
                if (reg_kind, ig_id) in instruction.regs:
                    return pass_obj.name, block.index, instr_idx, instruction
    return None


def _source_attribution_fact(attribution: Any) -> SourceAttributionFact:
    if attribution is None or attribution.source is None:
        return SourceAttributionFact(status="unattributed", confidence="unavailable")
    source = attribution.source
    status = _source_status(source)
    return SourceAttributionFact(
        status=status,
        symbol=source.name,
        expression=source.expression,
        kind=source.kind,
        source_file=source.source_file,
        line=source.source_line,
        column=source.source_col,
        confidence=source.confidence,
        compiler_temp=source.kind in {"compiler-temp", "temporary"},
    )


def _source_status(source: Any) -> str:
    if source is None:
        return "unattributed"
    if source.confidence in {"exact", "decl-order", "symbol-bridge", "copy-chain"}:
        return "attributed"
    if source.confidence in {"low", "ambiguous"}:
        return "ambiguous"
    return (
        "unattributed"
        if source.kind in {"implicit-temp", "copy/coalesce-product"}
        else "attributed"
    )


def _live_fact(attribution: Any) -> LiveFacts:
    if attribution is None:
        return LiveFacts(confidence="unavailable")
    interval = () if attribution.live_range is None else (attribution.live_range,)
    return LiveFacts(
        blocks=tuple(attribution.live_blocks),
        intervals=interval,
        confidence="observed",
    )


def _edges_from_ig(ig: Any) -> tuple[InterferenceEdge, ...]:
    edges: set[tuple[int, int]] = set()
    for node in ig.nodes.values():
        for neighbor in node.neighbors:
            if neighbor not in ig.nodes:
                continue
            a, b = sorted((node.ig_idx, neighbor))
            edges.add((a, b))
    return tuple(InterferenceEdge(a=a, b=b) for a, b in sorted(edges))


def _coalesce_payload(events: FunctionEvents, class_id: int) -> dict[str, Any]:
    mappings = [
        {"alias": alias, "root": root}
        for coalesce in events.coalesce_sections
        if coalesce.class_id == class_id
        for alias, root in coalesce.mappings
    ]
    for aliases in events.coalesced_alias_sections:
        if aliases.class_id != class_id:
            continue
        for alias, root, root_phys in aliases.aliases:
            record = {"alias": alias, "root": root, "root_phys": root_phys}
            if record not in mappings:
                mappings.append(record)
    return {"mappings": mappings}


def _node_flags(decision: Any, simplify: Any, ig_node: Any) -> tuple[str, ...]:
    flags: list[str] = []
    if decision is not None and decision.flags:
        flags.append(f"colorgraph:0x{decision.flags:02x}")
    if simplify is not None and simplify.flags:
        flags.append(f"simplify:0x{simplify.flags:02x}")
    if ig_node is not None and ig_node.incomplete:
        flags.append("incomplete_interferers")
    return tuple(flags)


def _node_from_mapping(payload: Any) -> AllocatorNode:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: nodes[]")
    _require_fields(
        payload,
        (
            "ig_id",
            "virtual",
            "color_status",
            "coalesced_into",
            "color_decision_ref",
            "assigned_phys",
            "simplify_order",
            "select_order",
            "first_def",
            "source_attribution",
            "live",
            "coalesce",
            "spill",
        ),
    )
    virtual = payload["virtual"]
    if not isinstance(virtual, Mapping):
        raise ValueError("backend trace missing required allocator facts: virtual")
    return AllocatorNode(
        ig_id=int(payload["ig_id"]),
        virtual_kind=str(_required(virtual, "kind")),
        virtual_number=int(_required(virtual, "number")),
        color_status=str(payload["color_status"]),
        coalesced_into=_maybe_int(payload.get("coalesced_into")),
        color_decision_ref=_maybe_str(payload.get("color_decision_ref")),
        first_def=_first_def_from_mapping(payload["first_def"]),
        source_attribution=_source_attr_from_mapping(payload["source_attribution"]),
        live=_live_from_mapping(payload["live"]),
        degree=int(payload.get("degree", 0)),
        flags=tuple(str(item) for item in payload.get("flags", ())),
        coalesce=_coalesce_facts_from_mapping(payload["coalesce"]),
        simplify_order=_maybe_int(payload.get("simplify_order")),
        select_order=_maybe_int(payload.get("select_order")),
        assigned_phys=_maybe_int(payload.get("assigned_phys")),
        spill=_spill_from_mapping(payload["spill"]),
    )


def _decision_from_mapping(payload: Any, *, index: int) -> ColorDecision:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: color_decisions[]")
    _require_fields(
        payload,
        (
            "id",
            "ig_id",
            "assigned_phys",
            "available_phys_ordered",
            "blocked_candidates",
            "candidate_phys_ordered",
            "chosen_source",
            "tie_rule",
            "decision_rule",
            "confidence",
            "provenance",
        ),
    )
    return ColorDecision(
        id=str(payload["id"]),
        ig_id=int(payload["ig_id"]),
        iter=int(payload.get("iter", index)),
        assigned_phys=_maybe_int(payload.get("assigned_phys")),
        available_phys_ordered=tuple(int(item) for item in payload["available_phys_ordered"]),
        blocked_candidates=tuple(
            _blocked_candidate_from_mapping(candidate)
            for candidate in payload["blocked_candidates"]
        ),
        candidate_phys_ordered=tuple(
            int(item) for item in payload["candidate_phys_ordered"]
        ),
        chosen_source=str(payload["chosen_source"]),
        decision_rule=str(payload["decision_rule"]),
        tie_rule=str(payload["tie_rule"]),
        confidence=str(payload["confidence"]),
        provenance=_maybe_str(payload.get("provenance")),
        blocked_by=tuple(
            _blocked_by_from_mapping(item) for item in payload.get("blocked_by", ())
        ),
        node_state_before_select=dict(payload.get("node_state_before_select", {})),
        volatile_pool_before=tuple(int(item) for item in payload.get("volatile_pool_before", ())),
        nonvolatile_pool_before={
            str(key): tuple(int(item) for item in value)
            for key, value in payload.get("nonvolatile_pool_before", {}).items()
        },
        reserved_or_precolored_filtered=tuple(
            int(item) for item in payload.get("reserved_or_precolored_filtered", ())
        ),
    )


def _registers_from_mapping(payload: Any) -> RegisterFacts:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: registers")
    _require_fields(
        payload,
        (
            "physical_count",
            "allocatable",
            "initial_volatile",
            "reserved",
            "nonvolatile_dispense_order",
            "fixed",
            "precolored",
            "model_boundary",
        ),
    )
    return RegisterFacts(
        physical_count=int(payload["physical_count"]),
        allocatable=tuple(int(item) for item in payload["allocatable"]),
        initial_volatile=tuple(int(item) for item in payload["initial_volatile"]),
        nonvolatile_dispense_order=tuple(
            int(item) for item in payload["nonvolatile_dispense_order"]
        ),
        reserved=tuple(int(item) for item in payload["reserved"]),
        fixed=tuple(dict(item) for item in payload["fixed"]),
        precolored=tuple(dict(item) for item in payload["precolored"]),
        model_boundary=tuple(dict(item) for item in payload["model_boundary"]),
    )


def _edge_from_mapping(payload: Any) -> InterferenceEdge:
    if isinstance(payload, Mapping):
        return InterferenceEdge(
            a=int(payload["a"]),
            b=int(payload["b"]),
            kind=str(payload.get("kind", "interference")),
            confidence=str(payload.get("confidence", "observed")),
        )
    return InterferenceEdge(a=int(payload[0]), b=int(payload[1]))


def _first_def_from_mapping(payload: Any) -> FirstDefSite | None:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: first_def")
    return FirstDefSite(
        pass_id=payload.get("pass_id"),
        block_id=payload.get("block_id"),
        instruction_id=payload.get("instruction_id"),
        opcode=payload.get("opcode"),
        operands=payload.get("operands"),
        normalized=payload.get("normalized"),
    )


def _source_attr_from_mapping(payload: Any) -> SourceAttributionFact:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: source_attribution")
    _require_fields(payload, ("status", "confidence"))
    return SourceAttributionFact(
        status=str(payload.get("status", "unattributed")),
        symbol=_maybe_str(payload.get("symbol")),
        expression=_maybe_str(payload.get("expression")),
        kind=_maybe_str(payload.get("kind")),
        source_file=_maybe_str(payload.get("source_file")),
        line=_maybe_int(payload.get("line")),
        column=_maybe_int(payload.get("column")),
        confidence=str(payload.get("confidence", "unavailable")),
        scope=_maybe_str(payload.get("scope")),
        compiler_temp=bool(payload.get("compiler_temp", False)),
    )


def _live_from_mapping(payload: Any) -> LiveFacts:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: live")
    _require_fields(payload, ("blocks", "intervals"))
    return LiveFacts(
        blocks=tuple(payload.get("blocks", ())),
        intervals=tuple(tuple(item) for item in payload.get("intervals", ())),
        confidence=str(payload.get("confidence", "observed")),
    )


def _coalesce_facts_from_mapping(payload: Any) -> CoalesceFacts:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: coalesce")
    return CoalesceFacts(
        root_ig_id=_maybe_int(payload.get("root_ig_id")),
        aliases=tuple(int(item) for item in payload.get("aliases", ())),
    )


def _spill_from_mapping(payload: Any) -> SpillFacts:
    if not isinstance(payload, Mapping):
        raise ValueError("backend trace missing required allocator facts: spill")
    _require_fields(payload, ("spilled",))
    return SpillFacts(
        spilled=bool(payload.get("spilled", False)),
        reason=_maybe_str(payload.get("reason")),
    )


def _blocked_candidate_from_mapping(payload: Any) -> BlockedCandidate:
    return BlockedCandidate(
        phys=int(payload["phys"]),
        holder_ig_id=_maybe_int(payload.get("holder_ig_id")),
        holder_assigned_phys=_maybe_int(payload.get("holder_assigned_phys")),
        reason=_maybe_str(payload.get("reason")),
    )


def _blocked_by_from_mapping(payload: Any) -> BlockedBy:
    return BlockedBy(
        ig_id=_maybe_int(payload.get("ig_id")),
        phys=_maybe_int(payload.get("phys")),
    )


def _register_policy(class_id: int) -> RegisterFacts:
    if class_id == 1:
        return RegisterFacts(
            physical_count=32,
            allocatable=tuple(range(32)),
            initial_volatile=tuple(range(14)),
            nonvolatile_dispense_order=tuple(range(31, 13, -1)),
        )
    return RegisterFacts(
        physical_count=32,
        allocatable=tuple(range(3, 32)),
        initial_volatile=tuple(range(3, 13)),
        nonvolatile_dispense_order=tuple(range(31, 12, -1)),
        reserved=(1, 2),
        fixed=({"phys": 1, "name": "sp"}, {"phys": 2, "name": "toc"}),
        model_boundary=({"phys": 0, "name": "r0"},),
    )


def _freshness(
    pcdump_path: str | Path | None,
    source_path: str | Path | None,
) -> FunctionFreshness:
    pcdump_mtime = _mtime(pcdump_path)
    source_mtime = _mtime(source_path)
    if pcdump_mtime is None or source_mtime is None:
        return FunctionFreshness(
            status="unknown",
            pcdump_mtime=pcdump_mtime,
            source_mtime=source_mtime,
        )
    return FunctionFreshness(
        status="fresh" if pcdump_mtime >= source_mtime else "stale",
        pcdump_mtime=pcdump_mtime,
        source_mtime=source_mtime,
    )


def _mtime(path: str | Path | None) -> float | None:
    if path is None:
        return None
    try:
        candidate = Path(path)
        if candidate.exists():
            return candidate.stat().st_mtime
    except OSError:
        return None
    return None


def _event_class_ids(events: FunctionEvents) -> tuple[int, ...]:
    class_ids = {
        section.class_id
        for section in events.colorgraph_sections
    } | {
        section.class_id
        for section in events.simplify_sections
    } | {
        section.class_id
        for section in events.coalesce_sections
    } | {
        section.class_id
        for section in events.coalesced_alias_sections
        if section.class_id >= 0
    }
    return tuple(sorted(class_ids))


def _decision_id(class_id: int, iter_idx: int) -> str:
    return f"class{class_id}-iter{iter_idx}"


def _blocked_phys(interferer: int, assigned: int) -> int | None:
    if interferer < 32:
        return interferer
    return assigned if assigned >= 0 else None


def _class_name(class_id: int) -> str:
    return "fpr" if class_id == 1 else "gpr"


def _path_str(path: str | Path | None) -> str | None:
    return None if path is None else str(path)


def _maybe_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _maybe_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _required(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValueError(f"backend trace missing required allocator facts: {key}")
    return payload[key]


def _require_fields(payload: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(
            "backend trace missing required allocator facts: " + ", ".join(missing)
        )


__all__ = [
    "facts_from_pcdump",
    "facts_from_backend_trace",
]
