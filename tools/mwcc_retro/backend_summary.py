"""Human-readable summaries for normalized mwcc-retro backend traces."""
from __future__ import annotations

from typing import Any


def _virt(node: dict[str, Any]) -> str:
    v = node.get("virtual") or {}
    return f"{v.get('kind', '?')}{v.get('number', '?')}"


def _decision_map(cls: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(dec.get("id")): dec
        for dec in cls.get("color_decisions", [])
        if isinstance(dec, dict) and dec.get("id") is not None
    }


def _blocked_summary(decision: dict[str, Any] | None) -> str:
    if not decision:
        return "blocked=-"
    pairs: list[str] = []
    for item in decision.get("blocked_by") or []:
        if not isinstance(item, dict):
            continue
        ig = item.get("ig_id")
        phys = item.get("phys")
        if ig is not None and phys is not None:
            pairs.append(f"{ig}:r{phys}")
    return "blocked=" + (",".join(pairs) if pairs else "-")


def render_regalloc_summary(trace: dict[str, Any]) -> str:
    out: list[str] = [f"schema {trace.get('schema_version')}", ""]
    for fn in trace.get("functions", []):
        out.append(f"function {fn.get('name')}")
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            class_name = cls.get("class_name")
            class_id = cls.get("class_id")
            out.append(f"  class {class_name}({class_id})")
            decisions = _decision_map(cls)
            for node in cls.get("nodes", []):
                ref = node.get("color_decision_ref")
                decision = decisions.get(str(ref)) if ref is not None else None
                status = node.get("color_status")
                root = node.get("coalesced_into")
                root_text = f" root={root}" if root is not None else ""
                out.append(
                    "    "
                    f"ig={node.get('ig_id')} virt={_virt(node)} "
                    f"phys=r{node.get('assigned_phys')} status={status}{root_text} "
                    f"degree={node.get('degree')} simplify={node.get('simplify_order')} "
                    f"select={node.get('select_order')} {_blocked_summary(decision)}"
                )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_backend_summary(trace: dict[str, Any]) -> str:
    out: list[str] = []
    for fn in trace.get("functions", []):
        out.append(f"BACKEND TRACE {fn.get('name')}")
        for p in (fn.get("pcode") or {}).get("passes", []):
            out.append(f"pass {p.get('id')}: {p.get('name')}")
            for inst in p.get("instructions", []):
                out.append(
                    f"  {inst.get('id')} {inst.get('block_id')} "
                    f"{inst.get('opcode')} {inst.get('operands')}"
                )
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            out.append(f"regalloc class {cls.get('class_name')}({cls.get('class_id')})")
            for edge in cls.get("edges", []):
                out.append(
                    f"  edge {edge.get('a')} -- {edge.get('b')} "
                    f"{edge.get('confidence')} {edge.get('provenance')}"
                )
    return "\n".join(out).rstrip() + "\n"
