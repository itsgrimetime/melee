"""Schema helpers for mwcc-retro backend trace v1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "mwcc-retro-backend-trace.v1"
STRUCT_MAP_SCHEMA_VERSION = "mwcc-retro-struct-map.v1"

REQUIRED_TOP = ("schema_version", "compiler", "source", "functions")
REQUIRED_REGISTER_FIELDS = (
    "physical_count",
    "allocatable",
    "initial_volatile",
    "reserved",
    "fixed",
    "precolored",
    "nonvolatile_dispense_order",
    "model_boundary",
)
REQUIRED_CLASS_FIELDS = (
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
)
REQUIRED_NODE_FIELDS = (
    "ig_id",
    "virtual",
    "first_def",
    "source_attribution",
    "live",
    "degree",
    "flags",
    "coalesce",
    "simplify_order",
    "select_order",
    "assigned_phys",
    "spill",
    "color_status",
    "coalesced_into",
    "color_decision_ref",
)
REQUIRED_COLOR_DECISION_FIELDS = (
    "id",
    "ig_id",
    "iter",
    "assigned_phys",
    "node_state_before_select",
    "reserved_or_precolored_filtered",
    "available_phys_ordered",
    "blocked_candidates",
    "candidate_phys_ordered",
    "chosen_source",
    "tie_rule",
    "decision_rule",
    "confidence",
    "provenance",
)
VALID_COLOR_STATUS = {
    "colored",
    "coalesced_alias",
    "spilled",
    "precolored",
    "uncolored",
}


def load_backend_trace(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def write_backend_trace(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def validate_backend_trace(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in _missing(payload, REQUIRED_TOP):
        errors.append(f"top-level missing {key}")

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION}, got {payload.get('schema_version')!r}"
        )

    compiler = payload.get("compiler") or {}
    if not isinstance(compiler, dict):
        errors.append("compiler must be object")
        compiler = {}
    else:
        if (
            compiler.get("family") != "MWCC"
            or compiler.get("version") != "GC/1.2.5n"
            or compiler.get("retail") is not True
        ):
            errors.append("compiler must describe retail MWCC GC/1.2.5n")

    functions = payload.get("functions")
    if not isinstance(functions, list) or not functions:
        errors.append("functions must be a non-empty list")
        return errors

    for fn_index, fn in enumerate(functions):
        if not isinstance(fn, dict):
            errors.append(f"function[{fn_index}] must be an object")
            continue

        fn_name = str(fn.get("name", fn_index))
        regalloc = fn.get("regalloc") or {}
        if not isinstance(regalloc, dict):
            errors.append(f"function {fn_name} regalloc must be object")
            continue
        classes = regalloc.get("classes")
        if not isinstance(classes, list) or not classes:
            errors.append(f"function {fn_name} missing regalloc classes")
            continue

        for cls in classes:
            if not isinstance(cls, dict):
                errors.append(f"{fn_name}:<unknown> class must be object")
                continue
            errors.extend(_validate_class(fn_name, cls))

    return errors


def _missing(mapping: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if key not in mapping]


def _validate_class(fn_name: str, cls: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    class_name = cls.get("class_name", cls.get("class_id", "<unknown>"))

    for key in _missing(cls, REQUIRED_CLASS_FIELDS):
        errors.append(f"{fn_name}:{class_name} missing {key}")

    _validate_registers(fn_name, class_name, cls.get("registers"), errors)

    nodes = cls.get("nodes")
    edges = cls.get("edges")
    decisions = cls.get("color_decisions")

    if not isinstance(nodes, list):
        errors.append(f"{fn_name}:{class_name} nodes must be a list")
        nodes = []
    if not isinstance(edges, list):
        errors.append(f"{fn_name}:{class_name} edges must be a list")
        edges = []
    if not isinstance(cls.get("simplify_order"), list):
        errors.append(f"{fn_name}:{class_name} simplify_order must be a list")
    if not isinstance(cls.get("select_order"), list):
        errors.append(f"{fn_name}:{class_name} select_order must be a list")
    if not isinstance(decisions, list):
        errors.append(f"{fn_name}:{class_name} color_decisions must be a list")
        decisions = []

    node_by_id = _index_nodes(fn_name, class_name, nodes, errors)
    decision_by_id = _index_decisions(fn_name, class_name, decisions, node_by_id, errors)
    _validate_edges(fn_name, class_name, edges, node_by_id, errors)
    _validate_coalesce(fn_name, class_name, cls.get("coalesce"), node_by_id, errors)
    _validate_nodes(fn_name, class_name, nodes, node_by_id, decision_by_id, errors)
    return errors


def _validate_registers(
    fn_name: str, class_name: Any, regs: Any, errors: list[str]
) -> None:
    if not isinstance(regs, dict):
        errors.append(f"{fn_name}:{class_name} missing registers")
        return

    for key in _missing(regs, REQUIRED_REGISTER_FIELDS):
        errors.append(f"{fn_name}:{class_name} registers missing {key}")

    for key in ("allocatable", "initial_volatile", "nonvolatile_dispense_order"):
        if isinstance(regs.get(key), list) and not regs[key]:
            errors.append(f"{fn_name}:{class_name} registers {key} must be non-empty")


def _index_nodes(
    fn_name: str,
    class_name: Any,
    nodes: list[Any],
    errors: list[str],
) -> dict[int, dict[str, Any]]:
    node_by_id: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ig_id = node.get("ig_id")
        if not isinstance(ig_id, int):
            continue
        if ig_id in node_by_id:
            errors.append(f"{fn_name}:{class_name} duplicate node ig_id {ig_id}")
        node_by_id[ig_id] = node
    return node_by_id


def _index_decisions(
    fn_name: str,
    class_name: Any,
    decisions: list[Any],
    node_by_id: dict[int, dict[str, Any]],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    decision_by_id: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append(f"{fn_name}:{class_name} color decision must be object")
            continue

        raw_id = decision.get("id")
        if raw_id is None:
            errors.append(f"{fn_name}:{class_name} color decision missing id")
            decision_id = "<missing-id>"
        else:
            decision_id = str(raw_id)
            if decision_id in seen:
                errors.append(f"{fn_name}:{class_name} duplicate color decision id {decision_id}")
            seen.add(decision_id)
            decision_by_id[decision_id] = decision

        for key in _missing(decision, REQUIRED_COLOR_DECISION_FIELDS):
            errors.append(f"{fn_name}:{class_name} color decision {decision_id} missing {key}")

        ig_id = decision.get("ig_id")
        if isinstance(ig_id, int) and ig_id not in node_by_id:
            errors.append(
                f"{fn_name}:{class_name} color decision {decision_id} references missing node {ig_id}"
            )

        blocked_candidates = decision.get("blocked_candidates", [])
        if not isinstance(blocked_candidates, list):
            errors.append(
                f"{fn_name}:{class_name} color decision {decision_id} "
                "blocked_candidates must be a list"
            )
            continue

        for blocked in blocked_candidates:
            if not isinstance(blocked, dict):
                continue
            holder = blocked.get("holder_ig_id")
            if isinstance(holder, int) and holder not in node_by_id:
                errors.append(
                    f"{fn_name}:{class_name} color decision {decision_id} "
                    f"blocked candidate holder {holder} missing"
                )

    return decision_by_id


def _validate_edges(
    fn_name: str,
    class_name: Any,
    edges: list[Any],
    node_by_id: dict[int, dict[str, Any]],
    errors: list[str],
) -> None:
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append(f"{fn_name}:{class_name} edge must be object")
            continue

        for endpoint in ("a", "b"):
            ig_id = edge.get(endpoint)
            if ig_id not in node_by_id:
                errors.append(f"{fn_name}:{class_name} edge references missing node {ig_id}")


def _validate_coalesce(
    fn_name: str,
    class_name: Any,
    coalesce: Any,
    node_by_id: dict[int, dict[str, Any]],
    errors: list[str],
) -> None:
    if not isinstance(coalesce, dict) or not isinstance(coalesce.get("mappings"), list):
        errors.append(f"{fn_name}:{class_name} coalesce.mappings must be a list")
        return

    for mapping in coalesce["mappings"]:
        if not isinstance(mapping, dict):
            errors.append(f"{fn_name}:{class_name} coalesce mapping must be object")
            continue

        alias = mapping.get("alias")
        root = mapping.get("root")
        if alias not in node_by_id:
            errors.append(
                f"{fn_name}:{class_name} coalesce mapping references missing alias {alias}"
            )
        if root not in node_by_id:
            errors.append(
                f"{fn_name}:{class_name} coalesce mapping references missing root {root}"
            )


def _validate_nodes(
    fn_name: str,
    class_name: Any,
    nodes: list[Any],
    node_by_id: dict[int, dict[str, Any]],
    decision_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            errors.append(f"{fn_name}:{class_name} node must be object")
            continue

        node_id = node.get("ig_id", "<missing-ig>")
        for key in _missing(node, REQUIRED_NODE_FIELDS):
            errors.append(f"{fn_name}:{class_name} node {node_id} missing {key}")

        status = node.get("color_status")
        if status not in VALID_COLOR_STATUS:
            errors.append(f"{fn_name}:{class_name} node {node_id} invalid color_status {status!r}")

        if status == "colored":
            _validate_colored_node(fn_name, class_name, node, decision_by_id, errors)
        elif status == "coalesced_alias":
            _validate_coalesced_alias(fn_name, class_name, node, node_by_id, errors)


def _validate_colored_node(
    fn_name: str,
    class_name: Any,
    node: dict[str, Any],
    decision_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    node_id = node.get("ig_id", "<missing-ig>")
    ref = node.get("color_decision_ref")
    decision = None
    if ref is None:
        errors.append(f"{fn_name}:{class_name} colored node {node_id} missing color_decision_ref")
    elif str(ref) not in decision_by_id:
        errors.append(
            f"{fn_name}:{class_name} colored node {node_id} references missing color decision {ref}"
        )
    else:
        decision = decision_by_id[str(ref)]
        if decision.get("ig_id") != node_id:
            errors.append(
                f"{fn_name}:{class_name} colored node {node_id} decision {ref} "
                f"has ig_id {decision.get('ig_id')}"
            )

    if node.get("assigned_phys") is None:
        errors.append(f"{fn_name}:{class_name} colored node {node_id} missing assigned_phys")
    elif decision is not None and node.get("assigned_phys") != decision.get("assigned_phys"):
        errors.append(
            f"{fn_name}:{class_name} colored node {node_id} assigned_phys "
            f"{node.get('assigned_phys')} does not match decision {ref} assigned_phys "
            f"{decision.get('assigned_phys')}"
        )

    if node.get("select_order") is None:
        errors.append(f"{fn_name}:{class_name} colored node {node_id} missing select_order")


def _validate_coalesced_alias(
    fn_name: str,
    class_name: Any,
    node: dict[str, Any],
    node_by_id: dict[int, dict[str, Any]],
    errors: list[str],
) -> None:
    node_id = node.get("ig_id", "<missing-ig>")
    root = node.get("coalesced_into")
    if root is None:
        errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} missing coalesced_into")
    elif root not in node_by_id:
        errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} references missing root {root}")
    elif node.get("assigned_phys") != node_by_id[root].get("assigned_phys"):
        errors.append(
            f"{fn_name}:{class_name} coalesced alias {node_id} assigned_phys "
            f"{node.get('assigned_phys')} does not match root {root} assigned_phys "
            f"{node_by_id[root].get('assigned_phys')}"
        )

    if node.get("assigned_phys") is None:
        errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} missing inherited assigned_phys")
