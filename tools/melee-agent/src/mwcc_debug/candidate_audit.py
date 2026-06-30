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


_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_CONTROL_WORDS = {
    "break",
    "case",
    "continue",
    "default",
    "do",
    "else",
    "for",
    "goto",
    "if",
    "return",
    "sizeof",
    "switch",
    "while",
}


_AGGREGATE_HEAD_RE = re.compile(
    r"(?s)^(?:typedef\s+)?(?:struct|union|enum)(?:\s+[A-Za-z_]\w*)?\s*$"
)


def _find_matching_brace(text: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(text)):
        ch = text[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _aggregate_body_ranges(masked: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"\{", masked):
        open_index = match.start()
        head_start = max(
            masked.rfind(";", 0, open_index),
            masked.rfind("{", 0, open_index),
            masked.rfind("}", 0, open_index),
        ) + 1
        head = masked[head_start:open_index].strip()
        if _AGGREGATE_HEAD_RE.match(head) is None:
            continue
        close_index = _find_matching_brace(masked, open_index)
        if close_index is not None:
            ranges.append((open_index + 1, close_index))
    return ranges


def _offset_in_ranges(offset: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _body_statements(masked: str) -> list[tuple[int, str]]:
    statements: list[tuple[int, str]] = []
    depth = 0
    start: int | None = None
    for index, ch in enumerate(masked):
        if ch == "{":
            if depth >= 1 and start is not None:
                head = masked[start:index]
                if head.strip():
                    statements.append((start, head))
            depth += 1
            start = index + 1
            continue
        if ch == "}":
            if depth >= 1 and start is not None:
                tail = masked[start:index]
                if tail.strip():
                    statements.append((start, tail))
            depth = max(0, depth - 1)
            start = index + 1 if depth >= 1 else None
            continue
        if ch == ";" and depth >= 1 and start is not None:
            statements.append((start, masked[start:index + 1]))
            start = index + 1
    return statements


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _split_top_level_initializer(text: str) -> tuple[str, str | None]:
    depth = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0:
            return text[:index], text[index + 1:]
    return text, None


def _parse_local_declaration(statement: str) -> list[tuple[str, str | None]]:
    stripped = statement.strip()
    if not stripped.endswith(";"):
        return []
    first = re.match(r"([A-Za-z_]\w*)\b", stripped)
    if first is None or first.group(1) in _CONTROL_WORDS:
        return []
    if re.match(r"[A-Za-z_]\w*\s*\(", stripped):
        return []

    match = re.match(
        r"(?s)^\s*(?:"
        r"(?:const|volatile|static|register|signed|unsigned|short|long|int|char|float|double|void|"
        r"s8|u8|s16|u16|s32|u32|s64|u64|f32|f64|bool|BOOL|"
        r"struct\s+[A-Za-z_]\w*|union\s+[A-Za-z_]\w*|enum\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
        r"(?:\s+|\s*\*+))+?"
        r"(?P<decls>.+?)\s*;\s*$",
        stripped,
    )
    if match is None:
        return []

    decls: list[tuple[str, str | None]] = []
    for raw_part in _split_top_level_commas(match.group("decls")):
        declarator, initializer = _split_top_level_initializer(raw_part)
        if "(" in declarator:
            continue
        name_match = re.search(
            r"\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*$",
            declarator.strip(),
        )
        if name_match is None:
            continue
        decls.append((name_match.group("name"), initializer))
    return decls


def _is_simple_assignment_lhs(text: str, start: int, end: int) -> bool:
    index = end
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "=":
        return False
    if index + 1 < len(text) and text[index + 1] == "=":
        return False
    return True


def _previous_nonspace_index(text: str, before: int) -> int:
    index = before - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index


def _is_member_access_identifier(text: str, start: int) -> bool:
    prev_index = _previous_nonspace_index(text, start)
    if prev_index < 0:
        return False
    if text[prev_index] == ".":
        return True
    if text[prev_index] != ">":
        return False
    arrow_start = _previous_nonspace_index(text, prev_index)
    return arrow_start >= 0 and text[arrow_start] == "-"


def _local_reads(text: str, known_locals: set[str]) -> list[tuple[str, int]]:
    reads: list[tuple[str, int]] = []
    for match in _IDENT_RE.finditer(text):
        name = match.group(0)
        if name not in known_locals:
            continue
        if _is_member_access_identifier(text, match.start()):
            continue
        if _is_simple_assignment_lhs(text, match.start(), match.end()):
            continue
        reads.append((name, match.start()))
    return reads


def _simple_assignment_defs(text: str, known_locals: set[str]) -> set[str]:
    defs: set[str] = set()
    for match in _IDENT_RE.finditer(text):
        name = match.group(0)
        if name not in known_locals:
            continue
        if _is_member_access_identifier(text, match.start()):
            continue
        if _is_simple_assignment_lhs(text, match.start(), match.end()):
            defs.add(name)
    return defs


def _simple_scalar_assignment(statement: str) -> tuple[str, str] | None:
    match = re.match(
        r"(?s)^\s*(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>[^;{}]+)\s*;\s*$",
        statement,
    )
    if match is None:
        return None
    return match.group("lhs"), match.group("rhs").strip()


def _identifier_names(text: str) -> set[str]:
    return {
        match.group(0)
        for match in _IDENT_RE.finditer(text)
        if match.group(0) not in _CONTROL_WORDS
    }


def _is_named_value_expr(expr: str) -> bool:
    canonical = _canonical_expr(expr)
    return bool(
        re.match(
            r"^[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\]]+\])*$",
            canonical,
        )
    )


def _raw_scalar_clobber_store_risks(masked: str) -> list[SourceRisk]:
    risks: list[SourceRisk] = []
    last_assignment: dict[str, tuple[str, str, int]] = {}
    seen: set[tuple[str, str, str]] = set()

    def process_assignment(name: str, rhs: str, start: int) -> None:
        rhs_reads = _identifier_names(rhs)
        for read_name in rhs_reads:
            last_assignment.pop(read_name, None)
        previous = last_assignment.get(name)
        rhs_key = _canonical_expr(rhs)
        if (
            previous is not None
            and _is_named_value_expr(previous[0])
            and _is_named_value_expr(rhs)
            and _canonical_expr(previous[0]) != rhs_key
        ):
            key = (name, _canonical_expr(previous[1]), rhs_key)
            if key not in seen:
                seen.add(key)
                excerpt = _line_excerpt(masked, start)
                risks.append(SourceRisk(
                    severity="reject",
                    kind="scalar-clobber-store",
                    name=name,
                    excerpt=excerpt,
                    semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
                    message=(
                        f"{name} is assigned from `{previous[0].strip()}` and "
                        f"then overwritten by `{rhs.strip()}` before any read; "
                        "this is a value-clobber behavior change"
                    ),
                ))
        last_assignment[name] = (rhs, _line_excerpt(masked, start), start)

    for start, statement in _body_statements(masked):
        declarations = _parse_local_declaration(statement)
        if declarations:
            for name, initializer in declarations:
                last_assignment.pop(name, None)
                if initializer is not None:
                    process_assignment(name, initializer, start)
            continue
        assignment = _simple_scalar_assignment(statement)
        if assignment is not None:
            process_assignment(assignment[0], assignment[1], start)
            continue
        for read_name in _identifier_names(statement):
            last_assignment.pop(read_name, None)
    return risks


def _scalar_clobber_store_risks(
    masked: str,
    base_masked: str | None,
) -> list[SourceRisk]:
    base_counts: Counter[tuple[str | None, str]] = Counter()
    if base_masked:
        base_counts.update(
            (risk.name, _canonical_expr(risk.excerpt or ""))
            for risk in _raw_scalar_clobber_store_risks(base_masked)
        )

    risks: list[SourceRisk] = []
    for risk in _raw_scalar_clobber_store_risks(masked):
        key = (risk.name, _canonical_expr(risk.excerpt or ""))
        if base_counts[key] > 0:
            base_counts[key] -= 1
            continue
        risks.append(risk)
    return risks


_CALL_STMT_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^;{}]*)\)\s*;"
)


def _conditional_depth_at(masked: str, offset: int) -> int:
    stack: list[bool] = []
    pending_conditional = False
    for match in re.finditer(r"\b(?:if|else)\b|[{}]", masked[:offset]):
        token = match.group(0)
        if token in {"if", "else"}:
            pending_conditional = True
        elif token == "{":
            stack.append(pending_conditional)
            pending_conditional = False
        elif token == "}" and stack:
            stack.pop()
            pending_conditional = False
    return sum(1 for item in stack if item)


def _call_arg_names(args: str) -> list[str]:
    names: list[str] = []
    for raw_arg in _split_top_level_commas(args):
        arg = raw_arg.strip()
        if re.match(r"^[A-Za-z_]\w*$", arg):
            names.append(arg)
    return names


def _canonical_call_signature(name: str, args: str) -> str:
    return f"{name}({_canonical_expr(args)})"


def _call_signature_with_arg_replaced(
    name: str,
    args: str,
    *,
    old: str,
    new: str,
) -> str:
    rendered: list[str] = []
    for raw_arg in _split_top_level_commas(args):
        arg = raw_arg.strip()
        rendered.append(new if arg == old else arg)
    return _canonical_call_signature(name, ",".join(rendered))


def _call_records(masked: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for match in _CALL_STMT_RE.finditer(masked):
        name = match.group("name")
        if name in _CONTROL_WORDS:
            continue
        args = match.group("args")
        records.append({
            "name": name,
            "args": args,
            "arg_names": _call_arg_names(args),
            "signature": _canonical_call_signature(name, args),
            "conditional_depth": _conditional_depth_at(masked, match.start()),
            "start": match.start(),
            "excerpt": _line_excerpt(masked, match.start()),
        })
    return records


def _call_hoist_into_conditional_risks(
    masked: str,
    base_masked: str | None,
) -> list[SourceRisk]:
    if not base_masked:
        return []
    base_unguarded = Counter(
        record["signature"]
        for record in _call_records(base_masked)
        if record["conditional_depth"] == 0
    )
    if not base_unguarded:
        return []
    candidate_records = _call_records(masked)
    candidate_unguarded = Counter(
        record["signature"]
        for record in candidate_records
        if record["conditional_depth"] == 0
    )
    risks: list[SourceRisk] = []
    seen: set[str] = set()
    for record in candidate_records:
        if record["conditional_depth"] == 0:
            continue
        signature = record["signature"]
        if base_unguarded[signature] <= candidate_unguarded[signature]:
            continue
        if signature in seen:
            continue
        seen.add(signature)
        risks.append(SourceRisk(
            severity="reject",
            kind="call-hoist-into-conditional",
            name=record["name"],
            excerpt=record["excerpt"],
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{record['name']} was unconditional in base.c but is guarded "
                "by a conditional in this candidate; this drops the call on "
                "the complementary path"
            ),
        ))
    return risks


def _alias_substitution_risks(
    masked: str,
    base_masked: str | None,
) -> list[SourceRisk]:
    if not base_masked:
        return []
    base_call_signatures = {
        record["signature"]
        for record in _call_records(base_masked)
    }
    base_alias_assignments = {
        _canonical_expr(statement)
        for _start, statement in _body_statements(base_masked)
        if _simple_scalar_assignment(statement) is not None
    }
    candidate_calls = _call_records(masked)
    risks: list[SourceRisk] = []
    seen: set[tuple[str, str, str]] = set()
    for start, statement in _body_statements(masked):
        assignment = _simple_scalar_assignment(statement)
        if assignment is None:
            continue
        alias, source = assignment
        if not re.match(r"^[A-Za-z_]\w*$", source) or alias == source:
            continue
        if _canonical_expr(statement) in base_alias_assignments:
            continue
        for record in candidate_calls:
            if record["start"] <= start:
                continue
            if alias not in record["arg_names"]:
                continue
            base_signature = _call_signature_with_arg_replaced(
                record["name"],
                record["args"],
                old=alias,
                new=source,
            )
            if base_signature not in base_call_signatures:
                continue
            key = (alias, source, record["signature"])
            if key in seen:
                continue
            seen.add(key)
            risks.append(SourceRisk(
                severity="reject",
                kind="alias-substitution",
                name=alias,
                excerpt=record["excerpt"],
                semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
                message=(
                    f"{alias} is newly aliased to {source} and then used in "
                    f"{record['name']} where base.c used {source}; this is an "
                    "unproven alias-substitution behavior change"
                ),
            ))
    return risks


_RAW_REGISTER_IDENTIFIER_RE = re.compile(
    r"\b(?:r(?:[0-9]|[12][0-9]|3[01])|f(?:[0-9]|[12][0-9]|3[01])|cr[0-7])\b"
)


def _declared_identifier_names(masked: str) -> set[str]:
    names: set[str] = set()
    for _start, statement in _body_statements(masked):
        for name, _initializer in _parse_local_declaration(statement):
            names.add(name)
    for match in re.finditer(r"\b[A-Za-z_]\w*\s*\((?P<params>[^;{}()]*)\)\s*\{", masked):
        for raw_param in _split_top_level_commas(match.group("params")):
            param = raw_param.strip()
            if not param or param == "void":
                continue
            name_match = re.search(
                r"\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$",
                param,
            )
            if name_match is not None:
                names.add(name_match.group("name"))
    return names


def _raw_register_identifier_risks(
    masked: str,
    base_masked: str | None,
) -> list[SourceRisk]:
    declared = _declared_identifier_names(masked)
    base_counts: Counter[str] = Counter()
    if base_masked:
        base_declared = _declared_identifier_names(base_masked)
        for match in _RAW_REGISTER_IDENTIFIER_RE.finditer(base_masked):
            name = match.group(0)
            if name not in base_declared:
                base_counts[name] += 1

    risks: list[SourceRisk] = []
    for match in _RAW_REGISTER_IDENTIFIER_RE.finditer(masked):
        name = match.group(0)
        if name in declared:
            continue
        if base_counts[name] > 0:
            base_counts[name] -= 1
            continue
        risks.append(SourceRisk(
            severity="reject",
            kind="raw-register-identifier",
            name=name,
            excerpt=_line_excerpt(masked, match.start()),
            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
            message=(
                f"{name} looks like an undeclared physical register token "
                "leaked into candidate C source"
            ),
        ))
    return risks


def _raw_use_before_def_risks(masked: str) -> list[SourceRisk]:
    risks: list[SourceRisk] = []
    seen: set[str] = set()
    known_locals: set[str] = set()
    defined_locals: set[str] = set()
    aggregate_ranges = _aggregate_body_ranges(masked)

    for start, statement in _body_statements(masked):
        if _offset_in_ranges(start, aggregate_ranges):
            continue
        declarations = _parse_local_declaration(statement)
        if declarations:
            for name, initializer in declarations:
                known_locals.add(name)
                if initializer is not None:
                    for read_name, read_offset in _local_reads(initializer, known_locals):
                        if read_name in defined_locals:
                            continue
                        key = f"{read_name}:{start + read_offset}"
                        if key in seen:
                            continue
                        seen.add(key)
                        risks.append(SourceRisk(
                            severity="reject",
                            kind="use-before-def",
                            name=read_name,
                            excerpt=_line_excerpt(masked, start + read_offset),
                            semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
                            message=(
                                f"{read_name} is read before any local assignment "
                                "or initializer in this candidate source"
                            ),
                        ))
                    defined_locals.add(name)
            continue

        for name, offset in _local_reads(statement, known_locals):
            if name in defined_locals:
                continue
            key = f"{name}:{start + offset}"
            if key in seen:
                continue
            seen.add(key)
            risks.append(SourceRisk(
                severity="reject",
                kind="use-before-def",
                name=name,
                excerpt=_line_excerpt(masked, start + offset),
                semantic_risk_bucket=SEMANTIC_BUCKET_HIGH,
                message=(
                    f"{name} is read before any local assignment or initializer "
                    "in this candidate source"
                ),
            ))
        defined_locals.update(_simple_assignment_defs(statement, known_locals))

    return risks


def _use_before_def_risks(masked: str, base_masked: str | None) -> list[SourceRisk]:
    base_counts: Counter[tuple[str | None, str]] = Counter()
    if base_masked:
        base_counts.update(
            (risk.name, _canonical_expr(risk.excerpt or ""))
            for risk in _raw_use_before_def_risks(base_masked)
        )

    risks: list[SourceRisk] = []
    for risk in _raw_use_before_def_risks(masked):
        key = (risk.name, _canonical_expr(risk.excerpt or ""))
        if base_counts[key] > 0:
            base_counts[key] -= 1
            continue
        risks.append(risk)
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
    risks.extend(_scalar_clobber_store_risks(masked, base_masked))
    risks.extend(_alias_substitution_risks(masked, base_masked))
    risks.extend(_call_hoist_into_conditional_risks(masked, base_masked))
    risks.extend(_raw_register_identifier_risks(masked, base_masked))
    risks.extend(_external_prototype_risks(masked, base_masked))
    risks.extend(_sign_risks(masked, base_masked))
    risks.extend(_use_before_def_risks(masked, base_masked))

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
