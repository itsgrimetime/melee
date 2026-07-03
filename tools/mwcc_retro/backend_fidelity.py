"""Retail-vs-debug backend trace comparison."""
from __future__ import annotations

from typing import Any


def _nodes(trace: dict[str, Any]) -> dict[tuple[str, int, int], dict[str, Any]]:
    out: dict[tuple[str, int, int], dict[str, Any]] = {}
    for fn in trace.get("functions", []):
        fn_name = fn.get("name")
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            class_id = int(cls.get("class_id", -1))
            for node in cls.get("nodes", []):
                out[(fn_name, class_id, int(node["ig_id"]))] = node
    return out


def compare_backend_traces(retail: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    retail_nodes = _nodes(retail)
    debug_nodes = _nodes(debug)
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
    for key in sorted(set(retail_nodes) | set(debug_nodes)):
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
            f"ig={diff['ig_id']} {diff['field']} "
            f"retail={diff['retail']} debug={diff['debug']}"
        )
    return "\n".join(out).rstrip() + "\n"
