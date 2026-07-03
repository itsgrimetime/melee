"""Retail-vs-debug backend trace comparison."""
from __future__ import annotations

from typing import Any


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
