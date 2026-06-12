"""Orchestrate a TU data-layout audit and attach suggestions/locations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .compare import Finding, compare_layout
from .objects import section_intervals, unit_paths
from .source_map import map_decls

_SUGGEST = {
    "split": "Model one object of the target size; reference sub-fields by offset.",
    "merge": "Split the source blob into the target's distinct objects.",
    "size-mismatch": "Resize the array/type to the target size.",
    "reorder": "Reorder the declarations to match target address order.",
    "section-mismatch": "Move the object to the target section (regular vs small-data: adjust type/const/size).",
    "binding-mismatch": "Fix static/global to match the target binding.",
    "missing": "Model this generated/literal object (unmodeled in source).",
    "anonymous": "Give this data a named declaration matching the production symbol.",
}


def suggest(f: Finding) -> str:
    return _SUGGEST.get(f.kind, "Investigate this data-layout discrepancy.")


@dataclass(frozen=True)
class EnrichedFinding:
    finding: Finding
    source_line: int | None
    suggestion: str


@dataclass(frozen=True)
class AuditResult:
    obj_path: str
    degraded: bool
    warnings: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    enriched: list[EnrichedFinding] = field(default_factory=list)


def audit_tu(repo: Path, c_file: Path, *, check_binding: bool = False) -> AuditResult:
    repo = Path(repo)
    up = unit_paths(repo, c_file)

    if not up.ref_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
            warnings=[f"reference object missing: {up.ref_obj} (degraded mode not in v1)"])
    if not up.our_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
            warnings=[f"current object missing: {up.our_obj}; build it first"])

    try:
        import elftools  # noqa: F401
    except ImportError:
        return AuditResult(up.obj_path, degraded=True,
            warnings=["pyelftools not installed; cannot read object symbols"])

    warnings: list[str] = []
    try:
        if up.our_obj.stat().st_mtime < Path(c_file).stat().st_mtime:
            warnings.append("current object older than source; rebuild for accuracy")
    except OSError:
        warnings.append("freshness unknown")

    target = section_intervals(up.ref_obj)
    current = section_intervals(up.our_obj)
    if not target and not current:
        warnings.append(
            "no data symbols read from either object; they may be unreadable or contain no data"
        )
    decls = map_decls(c_file)
    findings = compare_layout(target, current, check_binding=check_binding)

    enriched = []
    for f in findings:
        name = f.target[0] if f.target else None
        line = decls[name].line if name in decls else None
        enriched.append(EnrichedFinding(f, line, suggest(f)))

    return AuditResult(up.obj_path, degraded=False, warnings=warnings,
                       findings=findings, enriched=enriched)
