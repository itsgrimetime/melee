"""Render an AuditResult as text or JSON."""
from __future__ import annotations

import json

from .audit import AuditResult


def render_text(res: AuditResult) -> str:
    lines = [f"data-layout audit: {res.obj_path}"
             + ("  [DEGRADED]" if res.degraded else "")]
    for w in res.warnings:
        lines.append(f"  ! {w}")
    by_section: dict[str, list] = {}
    for ef in res.enriched:
        by_section.setdefault(ef.finding.section, []).append(ef)
    if not res.enriched:
        lines.append("  no data-layout discrepancies found")
    for section in sorted(by_section):
        lines.append(f"\n{section}")
        for ef in by_section[section]:
            f = ef.finding
            name = f.target[0] if f.target else "(gap)"
            loc = f" ({res.obj_path}.c:{ef.source_line})" if ef.source_line else ""
            lines.append(f"  [{f.kind}] {name}{loc}: {f.message}")
            lines.append(f"      -> {ef.suggestion}")
    return "\n".join(lines)


def render_json(res: AuditResult) -> str:
    return json.dumps({
        "obj_path": res.obj_path,
        "degraded": res.degraded,
        "warnings": res.warnings,
        "findings": [{
            "kind": ef.finding.kind,
            "section": ef.finding.section,
            "target": ef.finding.target,
            "current": ef.finding.current,
            "message": ef.finding.message,
            "confidence": ef.finding.confidence,
            "source_line": ef.source_line,
            "suggestion": ef.suggestion,
        } for ef in res.enriched],
    }, indent=2)
