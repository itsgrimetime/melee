"""Retail-vs-debug backend trace comparison."""
from __future__ import annotations

from typing import Any


def trace_from_mwcc_debug_pcdump(
    text: str,
    *,
    function: str,
    source: str,
) -> dict[str, Any]:
    """Adapt mwcc-debug pcdump colorgraph facts into a comparable trace shape.

    The returned payload is intentionally not a retail-valid backend trace:
    it uses ``compiler.retail = False`` and marks allocator decisions as
    ``debug-adapter`` because the debug DLL pcdump does not expose the full
    retail candidate ordering/pool state required by ``backend-trace.v1``.
    """

    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events

    parsed_events = parse_hook_events(text)
    parsed = find_function(parsed_events, function)
    if parsed is None:
        available = ", ".join(event.name for event in parsed_events) or "<none>"
        raise ValueError(
            f"mwcc-debug pcdump missing function {function}; available: {available}"
        )

    classes: list[dict[str, Any]] = []
    simplify_by_class = {
        section.class_id: {entry.ig_idx: entry for entry in section.entries}
        for section in parsed.simplify_sections
    }
    aliases_by_class = {
        section.class_id: section.aliases
        for section in parsed.coalesced_alias_sections
    }
    for section in parsed.colorgraph_sections:
        class_id = section.class_id
        class_name = "gpr" if class_id == 0 else "fpr"
        simplify_entries = simplify_by_class.get(class_id, {})
        alias_rows = aliases_by_class.get(class_id, [])
        alias_by_ig = {alias: (root, phys) for alias, root, phys in alias_rows}
        nodes: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        edge_keys: set[tuple[int, int]] = set()

        for decision in section.decisions:
            if decision.ig_idx < 0:
                continue
            decision_id = f"debug-c{class_id}-{decision.iter_idx}"
            simplify_entry = simplify_entries.get(decision.ig_idx)
            blocked_by = [
                {"ig_id": ig_id, "phys": phys}
                for ig_id, phys in decision.interferers
            ]
            blocked_candidates = [
                {
                    "phys": phys,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": ig_id,
                    "holder_assigned_phys": phys,
                    "provenance": "mwcc-debug-pcdump",
                }
                for ig_id, phys in decision.interferers
            ]
            for ig_id, _phys in decision.interferers:
                if ig_id >= 0 and ig_id != decision.ig_idx:
                    edge_keys.add(tuple(sorted((decision.ig_idx, ig_id))))

            root_tuple = alias_by_ig.get(decision.ig_idx)
            if root_tuple is None:
                color_status = "spilled" if decision.flags & 0x01 else "colored"
                coalesced_into = None
                color_decision_ref = decision_id
                assigned_phys = decision.assigned_reg
            else:
                root, root_phys = root_tuple
                color_status = "coalesced_alias"
                coalesced_into = root
                color_decision_ref = None
                assigned_phys = root_phys

            nodes.append(
                {
                    "ig_id": decision.ig_idx,
                    "virtual": {
                        "kind": "r" if class_id == 0 else "f",
                        "number": decision.ig_idx,
                    },
                    "first_def": {},
                    "source_attribution": {
                        "status": "unattributed",
                        "symbol": None,
                        "line": None,
                        "confidence": "unavailable",
                    },
                    "live": {
                        "blocks": [],
                        "intervals": [],
                        "confidence": "unavailable",
                    },
                    "degree": decision.degree,
                    "flags": [{"raw": decision.flags}] if decision.flags else [],
                    "coalesce": {
                        "root_ig_id": (
                            coalesced_into
                            if coalesced_into is not None
                            else decision.ig_idx
                        ),
                        "aliases": [],
                    },
                    "simplify_order": (
                        simplify_entry.iter_idx if simplify_entry is not None else None
                    ),
                    "select_order": decision.iter_idx,
                    "assigned_phys": assigned_phys,
                    "spill": {
                        "spilled": bool(decision.flags & 0x01),
                        "reason": "mwcc-debug-pcdump-flag"
                        if decision.flags & 0x01
                        else None,
                    },
                    "color_status": color_status,
                    "coalesced_into": coalesced_into,
                    "color_decision_ref": color_decision_ref,
                }
            )
            if color_status == "colored":
                decisions.append(
                    {
                        "id": decision_id,
                        "ig_id": decision.ig_idx,
                        "iter": decision.iter_idx,
                        "assigned_phys": decision.assigned_reg,
                        "node_state_before_select": {
                            "precolored": False,
                            "coalesced": False,
                            "spill_marked": bool(decision.flags & 0x01),
                            "rematerialized": False,
                        },
                        "reserved_or_precolored_filtered": [],
                        "available_phys_ordered": [],
                        "blocked_candidates": blocked_candidates,
                        "candidate_phys_ordered": [decision.assigned_reg],
                        "chosen_source": "observed-debug-assignment",
                        "tie_rule": "unavailable-debug-pcdump",
                        "decision_rule": "debug-pcdump-observed-assignment",
                        "confidence": "debug-adapter",
                        "provenance": "mwcc-debug-pcdump",
                        "blocked_by": blocked_by,
                    }
                )

        classes.append(
            {
                "class_id": class_id,
                "class_name": class_name,
                "registers": {
                    "physical_count": 32,
                    "allocatable": [],
                    "initial_volatile": [],
                    "reserved": [],
                    "fixed": [],
                    "precolored": [],
                    "nonvolatile_dispense_order": [],
                    "model_boundary": [],
                },
                "nodes": nodes,
                "edges": [
                    {
                        "a": a,
                        "b": b,
                        "kind": "interference",
                        "confidence": "debug-adapter",
                        "provenance": "mwcc-debug-pcdump",
                    }
                    for a, b in sorted(edge_keys)
                ],
                "coalesce": {
                    "mappings": [
                        {
                            "alias": alias,
                            "root": root,
                            "root_phys": root_phys,
                            "confidence": "debug-adapter",
                            "provenance": "mwcc-debug-pcdump",
                        }
                        for alias, root, root_phys in alias_rows
                    ]
                },
                "non_allocatable_state": {
                    "status": "debug-adapter-partial",
                    "notes": ["debug DLL pcdump comparison facts"],
                },
                "simplify_order": [
                    entry.ig_idx
                    for entry in sorted(
                        simplify_entries.values(), key=lambda entry: entry.iter_idx
                    )
                    if entry.ig_idx >= 0
                ],
                "select_order": [
                    node["ig_id"]
                    for node in sorted(
                        nodes,
                        key=lambda node: node["select_order"]
                        if node["select_order"] is not None
                        else -1,
                    )
                ],
                "color_decisions": decisions,
            }
        )

    return {
        "schema_version": "mwcc-retro-backend-trace.v1",
        "tool_version": "mwcc-debug-adapter",
        "compiler": {
            "family": "MWCC",
            "version": "GC/1.2.5n-debug-dll",
            "retail": False,
        },
        "source": {
            "tu": source,
            "function": function,
            "mwcc_command_hash": "mwcc-debug-pcdump",
        },
        "functions": [
            {
                "name": function,
                "identity": {
                    "requested": function,
                    "canonical_name": function,
                    "symbol_name": function,
                    "source_name": function,
                    "aliases": [],
                    "source_file": source,
                },
                "blocks": [],
                "pcode": {
                    "passes": [],
                    "instruction_identity_note": "debug adapter partial",
                },
                "regalloc": {"classes": classes},
            }
        ],
    }


def _record_not_comparable(report: dict[str, Any], record: dict[str, Any]) -> None:
    report["not_comparable"].append(record)
    report["summary"]["not_comparable"] += 1


def _nodes(
    trace: dict[str, Any],
    side: str,
    report: dict[str, Any],
) -> dict[tuple[str | None, int, int], dict[str, Any]]:
    functions = trace.get("functions") if isinstance(trace, dict) else None
    out: dict[tuple[str | None, int, int], dict[str, Any]] = {}
    if not isinstance(functions, list):
        _record_not_comparable(
            report, {"side": side, "reason": "functions must be list"}
        )
        return out

    for fn in functions:
        if not isinstance(fn, dict):
            _record_not_comparable(
                report, {"side": side, "reason": "function must be object"}
            )
            continue
        fn_name = fn.get("name")
        regalloc = fn.get("regalloc") or {}
        if not isinstance(regalloc, dict):
            _record_not_comparable(
                report,
                {
                    "side": side,
                    "function": fn_name,
                    "reason": "regalloc must be object",
                },
            )
            continue
        classes = regalloc.get("classes")
        if not isinstance(classes, list):
            _record_not_comparable(
                report,
                {
                    "side": side,
                    "function": fn_name,
                    "reason": "classes must be list",
                },
            )
            continue
        for cls in classes:
            if not isinstance(cls, dict):
                _record_not_comparable(
                    report,
                    {
                        "side": side,
                        "function": fn_name,
                        "reason": "class must be object",
                    },
                )
                continue
            try:
                class_id = int(cls.get("class_id", -1))
            except (TypeError, ValueError):
                _record_not_comparable(
                    report,
                    {
                        "side": side,
                        "function": fn_name,
                        "reason": "class_id must be int",
                    },
                )
                continue
            nodes = cls.get("nodes")
            if not isinstance(nodes, list):
                _record_not_comparable(
                    report,
                    {
                        "side": side,
                        "function": fn_name,
                        "class_id": class_id,
                        "reason": "nodes must be list",
                    },
                )
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    _record_not_comparable(
                        report,
                        {
                            "side": side,
                            "function": fn_name,
                            "class_id": class_id,
                            "reason": "node must be object",
                        },
                    )
                    continue
                if "ig_id" not in node:
                    _record_not_comparable(
                        report,
                        {
                            "side": side,
                            "function": fn_name,
                            "class_id": class_id,
                            "reason": "node missing ig_id",
                        },
                    )
                    continue
                try:
                    ig_id = int(node["ig_id"])
                except (TypeError, ValueError):
                    _record_not_comparable(
                        report,
                        {
                            "side": side,
                            "function": fn_name,
                            "class_id": class_id,
                            "reason": "node ig_id must be int",
                        },
                    )
                    continue
                out[(fn_name, class_id, ig_id)] = node
    return out


def compare_backend_traces(retail: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "mwcc-retro-backend-fidelity.v1",
        "summary": {
            "equal": 0,
            "retail_only": 0,
            "debug_only": 0,
            "different": 0,
            "not_comparable": 0,
        },
        "equal": [],
        "retail_only": [],
        "debug_only": [],
        "different": [],
        "not_comparable": [],
    }
    retail_nodes = _nodes(retail, "retail", report)
    debug_nodes = _nodes(debug, "debug", report)
    for key in sorted(set(retail_nodes) | set(debug_nodes), key=_node_key_sort):
        r = retail_nodes.get(key)
        d = debug_nodes.get(key)
        fn_name, class_id, ig_id = key
        if r is None:
            report["debug_only"].append(
                {"function": fn_name, "class_id": class_id, "ig_id": ig_id}
            )
            report["summary"]["debug_only"] += 1
            continue
        if d is None:
            report["retail_only"].append(
                {"function": fn_name, "class_id": class_id, "ig_id": ig_id}
            )
            report["summary"]["retail_only"] += 1
            continue
        for field in (
            "assigned_phys",
            "color_status",
            "degree",
            "simplify_order",
            "select_order",
        ):
            if r.get(field) == d.get(field):
                report["equal"].append(
                    {
                        "function": fn_name,
                        "class_id": class_id,
                        "ig_id": ig_id,
                        "field": field,
                    }
                )
                report["summary"]["equal"] += 1
            else:
                report["different"].append(
                    {
                        "function": fn_name,
                        "class_id": class_id,
                        "ig_id": ig_id,
                        "field": field,
                        "retail": r.get(field),
                        "debug": d.get(field),
                    }
                )
                report["summary"]["different"] += 1
    return report


def _node_key_sort(key: tuple[str | None, int, int]) -> tuple[str, int, int]:
    fn_name, class_id, ig_id = key
    return ("" if fn_name is None else str(fn_name), class_id, ig_id)


def render_fidelity_text(report: dict[str, Any]) -> str:
    s = report["summary"]
    out = [
        "backend fidelity report",
        f"equal: {s['equal']}",
        f"retail_only: {s['retail_only']}",
        f"debug_only: {s['debug_only']}",
        f"different: {s['different']}",
        f"not_comparable: {s['not_comparable']}",
        "",
    ]
    for diff in report.get("different", []):
        out.append(
            f"function={diff['function']} class_id={diff['class_id']} "
            f"ig={diff['ig_id']} {diff['field']} "
            f"retail={diff['retail']} debug={diff['debug']}"
        )
    return "\n".join(out).rstrip() + "\n"
