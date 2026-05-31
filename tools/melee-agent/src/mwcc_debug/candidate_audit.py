"""Classify decomp-permuter candidate source risk."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PERMUTER_PLACEHOLDERS = (
    "inline_fn",
    "noinline_fn",
    "extra_fn",
    "helper_fn",
    "temp_fn",
    "local_var_fn",
)

SEMANTIC_BUCKET_REPO_INVALID = "repo-invalid"
SEMANTIC_BUCKET_HIGH = "semantic-risk-high"
SEMANTIC_BUCKET_PLAUSIBLE = "plausible-C-shape"


@dataclass(frozen=True)
class SourceRisk:
    severity: str
    kind: str
    message: str
    name: str | None = None
    excerpt: str | None = None
    count: int | None = None
    semantic_risk_bucket: str | None = None


@dataclass(frozen=True)
class CandidateAudit:
    status: str
    risks: tuple[SourceRisk, ...]
    semantic_risk_bucket: str

    @property
    def should_reject(self) -> bool:
        return any(risk.severity == "reject" for risk in self.risks)


def placeholder_hits(text: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for placeholder in PERMUTER_PLACEHOLDERS:
        count = len(re.findall(r"\b" + re.escape(placeholder) + r"\b", text))
        if count:
            hits.append((placeholder, count))
    return hits


def risks_to_dicts(risks: tuple[SourceRisk, ...]) -> list[dict[str, Any]]:
    return [asdict(risk) for risk in risks]


def _mask_comments_and_strings(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append("\n" if ch == "\n" else " ")
            if ch == "\\" and i + 1 < n:
                out.append("\n" if text[i + 1] == "\n" else " ")
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(" ")
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                out.extend("  ")
                i += 2
                while i < n and text[i] != "\n":
                    out.append(" ")
                    i += 1
                continue
            if nxt == "*":
                out.extend("  ")
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    out.append("\n" if text[i] == "\n" else " ")
                    i += 1
                if i + 1 < n:
                    out.extend("  ")
                    i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _line_excerpt(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _canonical_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr.rstrip().rstrip(";"))


def _assignment_risks(
    masked: str,
    base_masked: str | None = None,
) -> list[SourceRisk]:
    risks: list[SourceRisk] = []
    repeated_seen: set[str] = set()
    repeated_re = re.compile(
        r"(?<![.>])\b(?P<name>[A-Za-z_]\w*)\s*=\s*\([^;\n{}]*\b(?P=name)\s*="
    )
    for match in repeated_re.finditer(masked):
        name = match.group("name")
        excerpt = _line_excerpt(masked, match.start())
        key = f"{name}:{excerpt}"
        if key in repeated_seen:
            continue
        repeated_seen.add(key)
        risks.append(SourceRisk(
            severity="reject",
            kind="repeated-scalar-assignment",
            name=name,
            excerpt=excerpt,
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{name} is assigned again inside its own assignment expression; "
                "this is unsafe/undefined candidate source"
            ),
        ))

    memory_self_re = re.compile(
        r"\b(?P<lhs>[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+"
        r"(?:\s*\[[^\]]+\])*)\s*=\s*(?P=lhs)\s*;"
    )
    for match in memory_self_re.finditer(masked):
        lhs_s = match.group("lhs").strip()
        risks.append(SourceRisk(
            severity="reject",
            kind="memory-self-assignment",
            name=lhs_s,
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{lhs_s} is assigned to itself through memory/pointer "
                "syntax; treat this as a side-effect-risk candidate"
            ),
        ))

    memory_compound_noop_re = re.compile(
        r"\b(?P<lhs>[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+"
        r"(?:\s*\[[^\]]+\])*)\s*(?P<op>\+=|-=|\*=|/=)\s*"
        r"(?P<value>[01](?:[uUlL]+)?)\s*;"
    )
    for match in memory_compound_noop_re.finditer(masked):
        op = match.group("op")
        value = match.group("value")[0]
        if (op in {"+=", "-="} and value != "0") or (
            op in {"*=", "/="} and value != "1"
        ):
            continue
        lhs_s = match.group("lhs").strip()
        risks.append(SourceRisk(
            severity="reject",
            kind="memory-compound-noop",
            name=lhs_s,
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{lhs_s} {op} {value} is a no-op write through "
                "memory/pointer syntax; treat this as a side-effect-risk "
                "candidate"
            ),
        ))

    scalar_self_re = re.compile(
        r"(?<![.>])\b(?P<name>[A-Za-z_]\w*)\s*=\s*(?P=name)\s*;"
    )
    base_scalar_self_counts: Counter[str] = Counter()
    if base_masked:
        base_scalar_self_counts.update(
            _canonical_expr(match.group(0))
            for match in scalar_self_re.finditer(base_masked)
        )
    for match in scalar_self_re.finditer(masked):
        name = match.group("name")
        expr_key = _canonical_expr(match.group(0))
        if base_scalar_self_counts[expr_key] > 0:
            base_scalar_self_counts[expr_key] -= 1
            continue
        risks.append(SourceRisk(
            severity="reject",
            kind="scalar-self-assignment",
            name=name,
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{name} = {name} is a local no-op perturbation; treat this "
                "as source-hostile candidate noise"
            ),
        ))
    return risks


def _abs_call_count(masked: str) -> int:
    return len(re.findall(r"\b(?:abs|labs|llabs|fabsf?|fabs)\s*\(", masked))


def _sign_risks(masked: str, base_masked: str | None) -> list[SourceRisk]:
    if not base_masked:
        return []

    risks: list[SourceRisk] = []
    candidate_abs_count = _abs_call_count(masked)
    base_abs_count = _abs_call_count(base_masked)
    if candidate_abs_count > base_abs_count:
        risks.append(SourceRisk(
            severity="reject",
            kind="abs-call-mutation",
            name="abs",
            count=candidate_abs_count - base_abs_count,
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                "candidate introduces abs-family calls not present in base.c; "
                "this can hide signedness/absolute-value semantic changes"
            ),
        ))

    manual_abs_flip_re = re.compile(
        r"\bif\s*\(\s*(?P<name>[A-Za-z_]\w*)\s*<\s*"
        r"(?:0(?:\.0+)?[fF]?)\s*\)\s*"
        r"(?:\{\s*)?"
        r"(?P=name)\s*=\s*-\s*(?P=name)\s*;\s*"
        r"(?:\}\s*)?"
        r"(?P=name)\s*=\s*-\s*(?P=name)\s*;",
        re.DOTALL,
    )
    base_manual_abs_flips = {
        _canonical_expr(match.group(0))
        for match in manual_abs_flip_re.finditer(base_masked)
    }
    seen_manual_abs_flips: set[str] = set()
    for match in manual_abs_flip_re.finditer(masked):
        expr = _canonical_expr(match.group(0))
        if expr in base_manual_abs_flips or expr in seen_manual_abs_flips:
            continue
        seen_manual_abs_flips.add(expr)
        name = match.group("name")
        risks.append(SourceRisk(
            severity="reject",
            kind="manual-abs-sign-flip",
            name=name,
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{name} is negated immediately after a manual absolute-value "
                "guard; this changes positive deltas into negative values"
            ),
        ))

    unsigned_compare_re = re.compile(
        r"\(\s*(?:u8|u16|u32|u64|unsigned(?:\s+(?:char|short|int|long))?)"
        r"\s*\)\s*[^;\n{}]*(?:<=|>=|<|>)"
    )
    base_unsigned_compares = {
        _canonical_expr(match.group(0))
        for match in unsigned_compare_re.finditer(base_masked)
    }
    seen: set[str] = set()
    for match in unsigned_compare_re.finditer(masked):
        expr = _canonical_expr(match.group(0))
        if expr in base_unsigned_compares or expr in seen:
            continue
        seen.add(expr)
        risks.append(SourceRisk(
            severity="reject",
            kind="unsigned-compare-mutation",
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                "candidate introduces an unsigned cast in a comparison not "
                "present in base.c; this is a sign-correctness risk"
            ),
        ))
    return risks


def _top_level_semicolon_decls(masked: str) -> list[tuple[int, str]]:
    decls: list[tuple[int, str]] = []
    depth = 0
    start = 0
    for index, ch in enumerate(masked):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                start = index + 1
        elif ch == ";" and depth == 0:
            decls.append((start, masked[start:index + 1]))
            start = index + 1
    return decls


def _canonical_prototype(decl: str) -> str:
    decl = re.sub(r"^\s*extern\s+", "", decl.strip())
    return re.sub(r"\s+", " ", decl).replace(" *", "*")


def _extract_top_level_prototypes(masked: str) -> dict[str, tuple[str, str]]:
    prototypes: dict[str, tuple[str, str]] = {}
    for _, decl in _top_level_semicolon_decls(masked):
        stripped = decl.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "typedef")):
            continue
        if "=" in stripped:
            continue
        match = re.match(
            r"(?s).+\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*;$",
            stripped,
        )
        if not match:
            continue
        name = match.group("name")
        if name in {"if", "for", "while", "switch", "return"}:
            continue
        prototypes[name] = (_canonical_prototype(stripped), stripped)
    return prototypes


def _external_prototype_risks(
    masked: str,
    base_masked: str | None,
) -> list[SourceRisk]:
    if not base_masked:
        return []
    base_prototypes = _extract_top_level_prototypes(base_masked)
    if not base_prototypes:
        return []
    candidate_prototypes = _extract_top_level_prototypes(masked)
    risks: list[SourceRisk] = []
    for name, (candidate_decl, candidate_excerpt) in candidate_prototypes.items():
        base = base_prototypes.get(name)
        if base is None:
            continue
        base_decl, base_excerpt = base
        if candidate_decl == base_decl:
            continue
        risks.append(SourceRisk(
            severity="reject",
            kind="external-prototype-mutation",
            name=name,
            excerpt=candidate_excerpt,
            semantic_risk_bucket=SEMANTIC_BUCKET_REPO_INVALID,
            message=(
                f"{name} top-level prototype changed from "
                f"`{base_excerpt}` to `{candidate_excerpt}`; permuter "
                "candidates must not require external TU declaration changes"
            ),
        ))
    return risks


def read_candidate_base_text(root: Path, *, max_parents: int = 4) -> str | None:
    path = root
    for _ in range(max_parents + 1):
        try:
            return (path / "base.c").read_text()
        except OSError:
            pass
        if path.parent == path:
            break
        path = path.parent
    return None


def semantic_risk_bucket_for_status(
    status: str,
    risks: tuple[SourceRisk, ...] = (),
) -> str:
    if any(risk.semantic_risk_bucket == SEMANTIC_BUCKET_REPO_INVALID for risk in risks):
        return SEMANTIC_BUCKET_REPO_INVALID
    if any(risk.semantic_risk_bucket == SEMANTIC_BUCKET_HIGH for risk in risks):
        return SEMANTIC_BUCKET_HIGH
    if status in {
        "build-failed",
        "corrupt-candidate",
        "no-function",
        "nonreproducible",
        "read-failed",
        "report-read-failed",
    }:
        return SEMANTIC_BUCKET_REPO_INVALID
    if risks:
        return SEMANTIC_BUCKET_HIGH
    return SEMANTIC_BUCKET_PLAUSIBLE


def audit_candidate_source(
    text: str,
    *,
    base_text: str | None = None,
) -> CandidateAudit:
    risks: list[SourceRisk] = []
    for placeholder, count in placeholder_hits(text):
        risks.append(SourceRisk(
            severity="reject",
            kind="placeholder-leak",
            name=placeholder,
            count=count,
            semantic_risk_bucket=SEMANTIC_BUCKET_REPO_INVALID,
            message=(
                f"{placeholder} appears in candidate source; decomp-permuter "
                "left an unresolved helper placeholder"
            ),
        ))

    masked = _mask_comments_and_strings(text)
    base_masked = _mask_comments_and_strings(base_text) if base_text else None
    risks.extend(_assignment_risks(masked, base_masked=base_masked))
    risks.extend(_external_prototype_risks(masked, base_masked))
    risks.extend(_sign_risks(masked, base_masked))

    if any(r.kind == "placeholder-leak" for r in risks):
        status = "corrupt-candidate"
    elif any(r.severity == "reject" for r in risks):
        status = "unsafe-candidate"
    elif risks:
        status = "diagnostic-only"
    else:
        status = "ok"
    risks_tuple = tuple(risks)
    return CandidateAudit(
        status=status,
        risks=risks_tuple,
        semantic_risk_bucket=semantic_risk_bucket_for_status(status, risks_tuple),
    )


def format_candidate_audit_diagnostic(
    report: CandidateAudit,
    *,
    command: str,
    candidate: Path | None = None,
) -> str:
    if not report.risks:
        return f"[{command}] candidate source audit passed"
    severity = "ABORT" if report.should_reject else "NOTE"
    summary = "; ".join(risk.message for risk in report.risks[:4])
    if len(report.risks) > 4:
        summary += f"; ... and {len(report.risks) - 4} more"
    message = f"[{command}] {severity}: {summary}"
    if candidate is not None:
        message += f" Candidate: {candidate}"
    return message


def status_sidecar_path(candidate: Path) -> Path:
    return candidate.parent / "melee-agent-candidate-status.json"


_STATUS_PRECEDENCE = {
    "ok": 0,
    "diagnostic-only": 1,
    "read-failed": 2,
    "corrupt-candidate": 3,
    "unsafe-candidate": 3,
    "build-failed": 4,
    "nonreproducible": 4,
    "report-read-failed": 4,
}


def _status_precedence(status: str | None) -> int:
    if status is None:
        return -1
    return _STATUS_PRECEDENCE.get(status, 0)


def _preserve_stronger_candidate_status(
    candidate: Path,
    *,
    fetch_payload: dict[str, Any],
) -> bool:
    path = status_sidecar_path(candidate)
    try:
        existing = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    existing_status = existing.get("status")
    fetch_status = fetch_payload.get("status")
    if _status_precedence(existing_status) <= _status_precedence(fetch_status):
        return False
    existing["fetch_audit"] = {
        key: fetch_payload.get(key)
        for key in (
            "status",
            "first_diag",
            "source_risks",
            "semantic_risk_bucket",
            "source",
            "function",
        )
        if key in fetch_payload
    }
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    return True


def write_candidate_status(
    candidate: Path,
    *,
    status: str,
    function: str | None = None,
    first_diag: str | None = None,
    risks: tuple[SourceRisk, ...] = (),
    match_pct: float | None = None,
    delta: float | None = None,
    semantic_risk_bucket: str | None = None,
    source: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    semantic_risk_bucket = semantic_risk_bucket or semantic_risk_bucket_for_status(
        status,
        risks,
    )
    payload: dict[str, Any] = {
        "candidate": str(candidate),
        "status": status,
        "function": function,
        "first_diag": first_diag,
        "match_pct": match_pct,
        "delta": delta,
        "semantic_risk_bucket": semantic_risk_bucket,
        "source_risks": risks_to_dicts(risks),
    }
    if source is not None:
        payload["source"] = source
    if extra:
        payload.update(extra)
    if source == "fetch" and _preserve_stronger_candidate_status(
        candidate,
        fetch_payload=payload,
    ):
        return status_sidecar_path(candidate)
    path = status_sidecar_path(candidate)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def audit_candidate_tree(root: Path, *, function: str | None = None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    base_text = read_candidate_base_text(root)
    for source in sorted(root.glob("output-*/source.c")):
        try:
            text = source.read_text()
        except OSError as exc:
            status = "read-failed"
            semantic_risk_bucket = semantic_risk_bucket_for_status(status)
            first_diag = f"{type(exc).__name__}: {exc}"
            risks: tuple[SourceRisk, ...] = ()
        else:
            report = audit_candidate_source(text, base_text=base_text)
            status = report.status
            semantic_risk_bucket = report.semantic_risk_bucket
            first_diag = (
                format_candidate_audit_diagnostic(
                    report,
                    command="fetch-perm",
                    candidate=source,
                )
                if report.risks else None
            )
            risks = report.risks
        counts[status] += 1
        bucket_counts[semantic_risk_bucket] += 1
        write_candidate_status(
            source,
            status=status,
            function=function,
            first_diag=first_diag,
            risks=risks,
            semantic_risk_bucket=semantic_risk_bucket,
            source="fetch",
        )
        candidates.append({
            "path": str(source),
            "status": status,
            "semantic_risk_bucket": semantic_risk_bucket,
            "first_diag": first_diag,
            "source_risks": risks_to_dicts(risks),
        })

    summary = {
        "root": str(root),
        "function": function,
        "total": len(candidates),
        "by_status": dict(sorted(counts.items())),
        "by_semantic_risk_bucket": dict(sorted(bucket_counts.items())),
        "candidates": candidates,
    }
    (root / "candidate_audit.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary
