"""Control-flow source-shape probe generation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from src.common import tree_sitter_c
from src.common.tree_sitter_c import find_function_definition, node_text

from .pressure_explorer import (
    LifetimeLayoutProbe,
    generate_lifetime_layout_probes,
)
from .source_spans import StatementSpan, list_statement_spans

DEFAULT_CONTROL_FLOW_OPERATORS = (
    "early-guard-return",
    "condition-nesting",
    "loop-init",
    "loop-counter-type",
    "guard-shape",
    "call-return-compare-chain",
    "pointer-walk-loop",
    "pointer-base-call-loop",
    "ternary-to-if-else",
    "if-else-to-ternary",
    "bool-condition-spelling",
)

_DELEGATED_OPERATORS = frozenset(DEFAULT_CONTROL_FLOW_OPERATORS) - {
    "ternary-to-if-else",
    "if-else-to-ternary",
    "bool-condition-spelling",
}
_LOCAL_OPERATORS = frozenset(DEFAULT_CONTROL_FLOW_OPERATORS) - _DELEGATED_OPERATORS

_IDENT = r"[A-Za-z_]\w*"
_SIMPLE_LHS_RE = re.compile(
    rf"^\s*{_IDENT}(?:(?:->|\.){_IDENT}|\[[A-Za-z0-9_+\-*/%&|^<>() \t]+\])*\s*$"
)
_ZERO_COMPARISON_RE = re.compile(r"^(.+?)\s*(==|!=)\s*0(?:[uUlL]*)?\s*$")
_CONTROL_FLOW_TOKENS = re.compile(r"\b(?:return|goto|break|continue)\b")
_ASSIGNMENT_TOKEN_RE = re.compile(r"(?<![=!<>])=(?!=)")
_PREPROCESSOR_IF_RE = re.compile(r"#\s*(?:if|ifdef|ifndef)\b")
_PREPROCESSOR_ENDIF_RE = re.compile(r"#\s*endif\b")


def generate_control_flow_shape_probes(
    source: str,
    function: str,
    *,
    operator_filter: Iterable[str] | None = None,
    max_probes: int = 12,
) -> list[LifetimeLayoutProbe]:
    probes, _status = scan_control_flow_shape_probes(
        source,
        function,
        operator_filter=operator_filter,
        max_probes=max_probes,
    )
    return probes


def scan_control_flow_shape_probes(
    source: str,
    function: str,
    *,
    operator_filter: Iterable[str] | None = None,
    max_probes: int = 12,
) -> tuple[list[LifetimeLayoutProbe], dict[str, object]]:
    selected = tuple(dict.fromkeys(operator_filter or DEFAULT_CONTROL_FLOW_OPERATORS))
    unsupported = [op for op in selected if op not in DEFAULT_CONTROL_FLOW_OPERATORS]
    if unsupported:
        return [], {
            "blocker": "unsupported-control-flow-shape",
            "reason": f"unsupported control-flow operators: {', '.join(unsupported)}",
            "supported_candidate_count": 0,
            "rejected_candidate_count": len(unsupported),
        }

    parsed = _parse_function(source, function)
    if parsed is None:
        return [], {
            "blocker": "ambiguous-control-flow-source-region",
            "reason": "function definition could not be located",
            "supported_candidate_count": 0,
            "rejected_candidate_count": 0,
        }

    source_bytes, function_node = parsed
    try:
        statement_spans = list_statement_spans(source, function)
    except Exception:
        statement_spans = []

    probes: list[LifetimeLayoutProbe] = []
    delegated = tuple(op for op in selected if op in _DELEGATED_OPERATORS)
    if delegated:
        probes.extend(
            _retag_control_flow_probe(probe)
            for probe in generate_lifetime_layout_probes(
                source,
                function,
                operator_filter=delegated,
                max_probes=max_probes,
            )
        )

    if len(probes) < max_probes:
        probes.extend(
            _local_control_flow_probes(
                source,
                function,
                source_bytes,
                function_node,
                statement_spans,
                tuple(op for op in selected if op in _LOCAL_OPERATORS),
                max_probes=max_probes - len(probes),
            )
        )

    probes = probes[:max_probes]
    if not probes:
        return [], {
            "blocker": "no-control-flow-shape-probes",
            "reason": "no safe control-flow source transform matched",
            "supported_candidate_count": 0,
            "rejected_candidate_count": 0,
        }
    return probes, {
        "blocker": None,
        "reason": "source scan generated safe control-flow shape probes",
        "supported_candidate_count": len(probes),
        "rejected_candidate_count": 0,
    }


def _parse_function(source: str, function: str) -> tuple[bytes, Any] | None:
    try:
        parser = tree_sitter_c.get_parser()
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return None
    function_node = find_function_definition(tree.root_node, source_bytes, function)
    if function_node is None:
        return None
    return source_bytes, function_node


def _retag_control_flow_probe(probe: LifetimeLayoutProbe) -> LifetimeLayoutProbe:
    provenance = dict(probe.provenance or {})
    provenance.setdefault("delegated_kind", provenance.get("kind", probe.operator))
    provenance["kind"] = "control-flow-shape"
    return LifetimeLayoutProbe(
        label=f"control-flow-{probe.label}",
        operator=probe.operator,
        description=probe.description,
        source_text=probe.source_text,
        provenance=provenance,
    )


def _local_control_flow_probes(
    source: str,
    function: str,
    source_bytes: bytes,
    function_node: Any,
    statement_spans: list[StatementSpan],
    operators: tuple[str, ...],
    *,
    max_probes: int,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for operator in operators:
        if operator == "ternary-to-if-else":
            candidates = _ternary_to_if_else_probes(source, source_bytes, statement_spans)
        elif operator == "if-else-to-ternary":
            candidates = _if_else_to_ternary_probes(source, source_bytes, function_node)
        elif operator == "bool-condition-spelling":
            candidates = _bool_condition_spelling_probes(source, source_bytes, function_node)
        else:
            candidates = []
        probes.extend(candidates[: max_probes - len(probes)])
        if len(probes) >= max_probes:
            break
    return probes


def _ternary_to_if_else_probes(
    source: str,
    source_bytes: bytes,
    statement_spans: list[StatementSpan],
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for span in statement_spans:
        if span.kind != "expression_statement":
            continue
        start, end = span.byte_range
        if _span_touches_preprocessor(source, start, end):
            continue
        statement_node = _parse_statement_node(source, span)
        if statement_node is None:
            continue
        assignment = _plain_assignment_expression_statement(statement_node, source_bytes)
        if assignment is None:
            continue
        lhs = assignment.child_by_field_name("left")
        rhs = assignment.child_by_field_name("right")
        if lhs is None or rhs is None or rhs.type != "conditional_expression":
            continue
        cond = rhs.child_by_field_name("condition")
        true_expr = rhs.child_by_field_name("consequence")
        false_expr = rhs.child_by_field_name("alternative")
        if cond is None or true_expr is None or false_expr is None:
            continue

        lhs_text = node_text(source_bytes, lhs).strip()
        cond_text = node_text(source_bytes, cond).strip()
        true_text = node_text(source_bytes, true_expr).strip()
        false_text = node_text(source_bytes, false_expr).strip()
        if not (
            _safe_expr(lhs_text, allow_lhs=True)
            and _safe_expr(cond_text)
            and _safe_expr(true_text)
            and _safe_expr(false_text)
        ):
            continue

        indent = _line_indent(source, start)
        replacement = (
            f"{indent}if ({cond_text}) {{\n"
            f"{indent}    {lhs_text} = {true_text};\n"
            f"{indent}}} else {{\n"
            f"{indent}    {lhs_text} = {false_text};\n"
            f"{indent}}}"
        )
        probes.append(
            _probe(
                "ternary-to-if-else",
                len(probes),
                "Expand ternary assignment to an if/else assignment.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _if_else_to_ternary_probes(source: str, source_bytes: bytes, function_node: Any) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for node in _walk_nodes(function_node, {"if_statement"}):
        start, end = node.start_byte, node.end_byte
        if _span_touches_preprocessor(source, start, end):
            continue
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        alt_compound = _else_compound(alternative)
        if (
            condition is None
            or consequence is None
            or consequence.type != "compound_statement"
            or alt_compound is None
        ):
            continue
        true_assign = _single_assignment_statement(consequence, source_bytes)
        false_assign = _single_assignment_statement(alt_compound, source_bytes)
        if true_assign is None or false_assign is None:
            continue
        lhs, true_expr = true_assign
        false_lhs, false_expr = false_assign
        cond_text = _strip_outer_parens(node_text(source_bytes, condition).strip())
        if lhs != false_lhs:
            continue
        if not (
            _safe_expr(lhs, allow_lhs=True)
            and _safe_expr(cond_text)
            and _safe_expr(true_expr)
            and _safe_expr(false_expr)
        ):
            continue

        indent = _line_indent(source, start)
        replacement = f"{indent}{lhs} = {cond_text} ? {true_expr} : {false_expr};"
        probes.append(
            _probe(
                "if-else-to-ternary",
                len(probes),
                "Collapse simple if/else assignment to a ternary assignment.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _bool_condition_spelling_probes(source: str, source_bytes: bytes, function_node: Any) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for node in _walk_nodes(function_node, {"if_statement", "while_statement"}):
        condition = node.child_by_field_name("condition")
        if condition is None:
            continue
        start, end = condition.start_byte, condition.end_byte
        if _span_touches_preprocessor(source, start, end):
            continue
        cond_text = _strip_outer_parens(node_text(source_bytes, condition).strip())
        replacement_inner = _boolean_condition_alternative(cond_text)
        if replacement_inner is None:
            continue
        replacement = f"({replacement_inner})"
        probes.append(
            _probe(
                "bool-condition-spelling",
                len(probes),
                "Spell boolean condition as an explicit zero comparison.",
                _replace_slice(source, start, end, replacement),
                source,
                start,
                end,
            )
        )
    return probes


def _boolean_condition_alternative(cond_text: str) -> str | None:
    cond_text = cond_text.strip()
    if cond_text.startswith("!"):
        inner = cond_text[1:].strip()
        inner = _strip_outer_parens(inner)
        if _safe_bool_operand(inner):
            return f"{inner} == 0"
        return None
    comparison = _ZERO_COMPARISON_RE.fullmatch(cond_text)
    if comparison is not None:
        inner = _strip_outer_parens(comparison.group(1).strip())
        operator = comparison.group(2)
        if not _safe_bool_operand(inner):
            return None
        if operator == "==":
            return f"!{inner}"
        return inner
    if _safe_bool_operand(cond_text):
        return f"{cond_text} != 0"
    return None


def _safe_bool_operand(expr: str) -> bool:
    expr = _strip_outer_parens(expr.strip())
    return _safe_expr(expr, allow_lhs=True)


def _parse_statement_node(source: str, span: StatementSpan) -> Any | None:
    try:
        source_bytes = source.encode("utf-8")
        tree = tree_sitter_c.get_parser().parse(source_bytes)
    except Exception:
        return None
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.start_byte == span.byte_range[0] and node.end_byte == span.byte_range[1]:
            return node
        stack.extend(reversed(node.children))
    return None


def _single_assignment_statement(compound: Any, source_bytes: bytes) -> tuple[str, str] | None:
    statements = [
        child
        for child in compound.children
        if child.type not in {"{", "}", "comment"} and child.is_named
    ]
    if len(statements) != 1 or statements[0].type != "expression_statement":
        return None
    assignment = _plain_assignment_expression_statement(statements[0], source_bytes)
    if assignment is None:
        return None
    lhs = assignment.child_by_field_name("left")
    rhs = assignment.child_by_field_name("right")
    if lhs is None or rhs is None:
        return None
    return node_text(source_bytes, lhs).strip(), node_text(source_bytes, rhs).strip()


def _safe_expr(expr: str, *, allow_lhs: bool = False) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if _CONTROL_FLOW_TOKENS.search(expr):
        return False
    if any(token in expr for token in ("++", "--", "{", "}", ":")):
        return False
    if "," in expr or _ASSIGNMENT_TOKEN_RE.search(expr):
        return False
    if not _balanced_delimiters(expr):
        return False
    if allow_lhs:
        return _SIMPLE_LHS_RE.fullmatch(expr) is not None and "(" not in expr and ")" not in expr
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return False
    return True


def _span_touches_preprocessor(source: str, start: int, end: int) -> bool:
    char_start, char_end = _byte_to_char_range(source, start, end)
    line_start = source.rfind("\n", 0, char_start) + 1
    line_end = source.find("\n", char_end)
    if line_end == -1:
        line_end = len(source)
    covered = source[line_start:line_end]
    if any(re.match(r"\s*#", line) for line in covered.splitlines()):
        return True

    return _inside_preprocessor_region(source, char_start)


def _inside_preprocessor_region(source: str, char_index: int) -> bool:
    depth = 0
    for line in source[:char_index].splitlines():
        stripped = line.lstrip()
        if _PREPROCESSOR_IF_RE.match(stripped):
            depth += 1
        elif _PREPROCESSOR_ENDIF_RE.match(stripped) and depth:
            depth -= 1
    return depth > 0


def _is_plain_assignment(assignment: Any, source_bytes: bytes) -> bool:
    operator = assignment.child_by_field_name("operator")
    return operator is not None and node_text(source_bytes, operator).strip() == "="


def _plain_assignment_expression_statement(statement: Any, source_bytes: bytes) -> Any | None:
    named_children = [
        child
        for child in statement.children
        if child.is_named and child.type != "comment"
    ]
    if len(named_children) != 1 or named_children[0].type != "assignment_expression":
        return None
    assignment = named_children[0]
    if not _is_plain_assignment(assignment, source_bytes):
        return None
    return assignment


def _line_range(source: str, start: int, end: int) -> tuple[int, int]:
    char_start, char_end = _byte_to_char_range(source, start, end)
    return source.count("\n", 0, char_start) + 1, source.count("\n", 0, char_end) + 1


def _replace_slice(source: str, start: int, end: int, replacement: str) -> str:
    char_start, char_end = _byte_to_char_range(source, start, end)
    return source[:char_start] + replacement + source[char_end:]


def _probe(
    operator: str,
    index: int,
    description: str,
    source_text: str,
    original_source: str,
    start: int,
    end: int,
) -> LifetimeLayoutProbe:
    return LifetimeLayoutProbe(
        label=f"control-flow-{operator}-{index}",
        operator=operator,
        description=description,
        source_text=source_text,
        provenance={
            "kind": "control-flow-shape",
            "operator": operator,
            "lines": list(_line_range(original_source, start, end)),
            "byte_range": [start, end],
        },
    )


def _walk_nodes(node: Any, types: set[str]) -> list[Any]:
    out: list[Any] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            out.append(current)
        stack.extend(reversed(current.children))
    return sorted(out, key=lambda item: item.start_byte)


def _first_child_of_type(node: Any, node_type: str) -> Any | None:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        stack.extend(reversed(current.children))
    return None


def _else_compound(alternative: Any | None) -> Any | None:
    if alternative is None or alternative.type != "else_clause":
        return None
    for child in alternative.children:
        if child.type == "compound_statement":
            return child
    return None


def _line_indent(source: str, start: int) -> str:
    char_start = _byte_to_char_range(source, start, start)[0]
    line_start = source.rfind("\n", 0, char_start) + 1
    indent = source[line_start:char_start]
    if indent:
        return indent
    return "    "


def _strip_outer_parens(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")") and _outer_parens_wrap(expr):
        expr = expr[1:-1].strip()
    return expr


def _outer_parens_wrap(expr: str) -> bool:
    depth = 0
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and idx != len(expr) - 1:
                return False
        if depth < 0:
            return False
    return depth == 0


def _balanced_delimiters(expr: str) -> bool:
    pairs = {")": "(", "]": "["}
    stack: list[str] = []
    for char in expr:
        if char in "([":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


def _byte_to_char_range(source: str, start: int, end: int) -> tuple[int, int]:
    encoded = source.encode("utf-8")
    prefix_start = encoded[:start].decode("utf-8", errors="ignore")
    prefix_end = encoded[:end].decode("utf-8", errors="ignore")
    return len(prefix_start), len(prefix_end)
