"""Source probes for pcode-only global pointer load lifetimes."""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from collections.abc import Mapping
from typing import Any

from src.search.directed.anchors import Anchor
from src.search.directed.transform_corpus.common import (
    _blank_literals_and_comments,
    _target_function_body,
)


MUTATOR_KEY = "steer_pcode_only_gpr_global_load_lifetime"


@dataclass(frozen=True)
class _PointerGlobalDecl:
    name: str
    type_text: str
    line_no: int


@dataclass(frozen=True)
class _GlobalUse:
    global_name: str
    start: int
    end: int
    text: str
    replacement: str
    kind: str
    line_no: int


def iter_global_load_lifetime_anchors(
    source_text: str,
    *,
    function: str,
    force_phys: Mapping[int, int],
    max_candidates: int,
    global_types: Mapping[str, str] | None = None,
) -> tuple[Anchor, ...]:
    target = _target_function_body(source_text, function)
    if target is None or max_candidates <= 0:
        return ()
    span, _body_text = target
    decls = _pointer_global_decls(source_text, before_offset=span.sig_start)
    for name, type_text in (global_types or {}).items():
        if "*" not in type_text:
            continue
        decls.setdefault(name, _PointerGlobalDecl(
            name=name,
            type_text=_clean_type_text(type_text),
            line_no=0,
        ))
    if not decls:
        return ()

    candidate_rows: list[tuple[Anchor, str]] = []
    seen: set[str] = set()
    for decl in sorted(decls.values(), key=lambda item: item.name):
        if len(candidate_rows) >= max_candidates:
            break
        uses = _global_uses(source_text, span.body_open, span.body_close, decl)
        if not uses:
            continue
        for strategy, selected in _strategy_use_sets(uses):
            if len(candidate_rows) >= max_candidates:
                break
            row = _candidate_for_strategy(
                source_text,
                function=function,
                function_start=span.sig_start,
                function_end=span.full_end,
                body_open=span.body_open,
                global_decl=decl,
                strategy=strategy,
                selected=selected,
                force_phys=force_phys,
                ordinal=len(candidate_rows),
            )
            if row is None:
                continue
            anchor, candidate_text = row
            if candidate_text in seen:
                continue
            seen.add(candidate_text)
            candidate_rows.append(row)
    return tuple(anchor for anchor, _candidate_text in candidate_rows)


def global_load_lifetime_match_diagnostics(
    source_text: str | None,
    *,
    function: str,
    force_phys: Mapping[int, int],
    anchors: tuple[Anchor, ...],
    global_types: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if source_text is None:
        return {
            "status": "blocked",
            "terminal_blocker": "source-unavailable",
            "accepted_anchor_count": 0,
        }
    target = _target_function_body(source_text, function)
    if target is None:
        return {
            "status": "blocked",
            "terminal_blocker": "function-not-found",
            "accepted_anchor_count": 0,
        }
    span, _body_text = target
    decls = _pointer_global_decls(source_text, before_offset=span.sig_start)
    for name, type_text in (global_types or {}).items():
        if "*" in type_text:
            decls.setdefault(name, _PointerGlobalDecl(
                name=name,
                type_text=_clean_type_text(type_text),
                line_no=0,
            ))
    use_counts = {
        name: len(_global_uses(source_text, span.body_open, span.body_close, decl))
        for name, decl in decls.items()
    }
    return {
        "status": "materialized" if anchors else "blocked",
        "terminal_blocker": None if anchors else "no-pointer-global-load-uses",
        "requested_force_phys": {str(ig): int(phys) for ig, phys in sorted(force_phys.items())},
        "pointer_global_count": len(decls),
        "pointer_global_use_counts": use_counts,
        "accepted_anchor_count": len(anchors),
        "strategies": sorted(
            {
                str(anchor.payload.get("strategy"))
                for anchor in anchors
                if anchor.payload.get("strategy")
            }
        ),
    }


def _pointer_global_decls(
    source_text: str,
    *,
    before_offset: int,
) -> dict[str, _PointerGlobalDecl]:
    prefix = _top_level_text(source_text[:before_offset])
    pattern = re.compile(
        r"(?m)^[ \t]*(?:extern\s+|static\s+)?"
        r"(?P<type>(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*)+)\s*"
        r"(?P<name>[A-Za-z_]\w*)\s*;\s*$"
    )
    decls: dict[str, _PointerGlobalDecl] = {}
    for match in pattern.finditer(prefix):
        type_text = _clean_type_text(match.group("type"))
        name = match.group("name")
        decls[name] = _PointerGlobalDecl(
            name=name,
            type_text=type_text,
            line_no=prefix.count("\n", 0, match.start()) + 1,
        )
    return decls


def _clean_type_text(type_text: str) -> str:
    return re.sub(r"\s+", " ", type_text).replace(" *", "*").strip()


def _top_level_text(text: str) -> str:
    result: list[str] = []
    depth = 0
    in_block_comment = False
    for line in text.splitlines(keepends=True):
        at_top = depth == 0 and not in_block_comment
        result.append(line if at_top else "".join("\n" if ch == "\n" else " " for ch in line))
        idx = 0
        in_string: str | None = None
        while idx < len(line):
            ch = line[idx]
            nxt = line[idx + 1] if idx + 1 < len(line) else ""
            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    idx += 2
                    continue
                idx += 1
                continue
            if in_string is not None:
                if ch == "\\":
                    idx += 2
                    continue
                if ch == in_string:
                    in_string = None
                idx += 1
                continue
            if ch in {'"', "'"}:
                in_string = ch
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                idx += 2
                continue
            elif ch == "/" and nxt == "/":
                break
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
            idx += 1
    return "".join(result)


def _global_uses(
    source_text: str,
    body_open: int,
    body_close: int,
    decl: _PointerGlobalDecl,
) -> tuple[_GlobalUse, ...]:
    body = source_text[body_open:body_close]
    searchable = _blank_literals_and_comments(body)
    global_name = decl.name
    alias_name = _alias_name(global_name, 0)
    member_pattern = re.compile(
        r"(?<![A-Za-z0-9_\"'])"
        + re.escape(global_name)
        + r"\s*->\s*(?P<field>[A-Za-z_]\w*)"
    )
    bare_pattern = re.compile(
        r"(?<![A-Za-z0-9_\"'.>-])"
        + re.escape(global_name)
        + r"(?!\s*->|\s*\.)\b"
    )
    uses: list[_GlobalUse] = []
    for match in member_pattern.finditer(searchable):
        text = body[match.start():match.end()]
        field = match.group("field")
        uses.append(_GlobalUse(
            global_name=global_name,
            start=body_open + match.start(),
            end=body_open + match.end(),
            text=text,
            replacement=f"{alias_name}->{field}",
            kind="member",
            line_no=source_text.count("\n", 0, body_open + match.start()) + 1,
        ))
    for match in bare_pattern.finditer(searchable):
        absolute_start = body_open + match.start()
        absolute_end = body_open + match.end()
        if any(use.start <= absolute_start < use.end for use in uses):
            continue
        if not _safe_bare_global_use(source_text, absolute_start, absolute_end):
            continue
        uses.append(_GlobalUse(
            global_name=global_name,
            start=absolute_start,
            end=absolute_end,
            text=body[match.start():match.end()],
            replacement=alias_name,
            kind="bare",
            line_no=source_text.count("\n", 0, absolute_start) + 1,
        ))
    uses.sort(key=lambda use: (use.start, use.end))
    return tuple(uses)


def _strategy_use_sets(uses: tuple[_GlobalUse, ...]) -> tuple[tuple[str, tuple[_GlobalUse, ...]], ...]:
    first_member = next((use for use in uses if use.kind == "member"), None)
    if first_member is None:
        return ()
    first_and_next_bare = tuple(
        use
        for use in uses
        if use is first_member or (use.kind == "bare" and use.start > first_member.start)
    )[:3]
    rows: list[tuple[str, tuple[_GlobalUse, ...]]] = [
        ("alias-first-member-use", (first_member,)),
    ]
    if len(first_and_next_bare) > 1:
        rows.append(("alias-first-and-call-uses", first_and_next_bare))
    later_alias = next(
        (
            use
            for use in uses
            if use.kind == "bare" and use.start > first_member.start
        ),
        None,
    )
    if later_alias is not None:
        rows.append(("hoist-existing-alias-init", (first_member, later_alias)))
    return tuple(rows)


def _candidate_for_strategy(
    source_text: str,
    *,
    function: str,
    function_start: int,
    function_end: int,
    body_open: int,
    global_decl: _PointerGlobalDecl,
    strategy: str,
    selected: tuple[_GlobalUse, ...],
    force_phys: Mapping[int, int],
    ordinal: int,
) -> tuple[Anchor, str] | None:
    del ordinal
    alias_name = _alias_name(global_decl.name, 0)
    alias_decl_line = f"    {global_decl.type_text} {alias_name};"
    insert_offset = _declaration_insert_offset(source_text, body_open)
    if insert_offset is None or alias_name in source_text[function_start:function_end]:
        return None
    first_use = min(selected, key=lambda use: use.start)
    assign_offset = _line_start_for_offset(source_text, first_use.start)
    assign_indent = _line_indent_at(source_text, assign_offset)
    alias_assign_line = f"{assign_indent}{alias_name} = {global_decl.name};"
    edits = [{
        "start": insert_offset,
        "end": insert_offset,
        "span_text": "",
        "replacement_text": alias_decl_line + "\n",
        "kind": "insert-global-alias-declaration",
        "line_no": source_text.count("\n", 0, insert_offset) + 1,
    }, {
        "start": assign_offset,
        "end": assign_offset,
        "span_text": "",
        "replacement_text": alias_assign_line + "\n",
        "kind": "insert-global-alias-assignment",
        "line_no": source_text.count("\n", 0, assign_offset) + 1,
    }]
    for use in selected:
        replacement = use.replacement.replace(_alias_name(global_decl.name, 0), alias_name)
        edits.append({
            "start": use.start,
            "end": use.end,
            "span_text": use.text,
            "replacement_text": replacement,
            "kind": f"rewrite-{use.kind}-global-use",
            "line_no": use.line_no,
        })
    candidate_text = _apply_edits(source_text, edits)
    if candidate_text is None or candidate_text == source_text:
        return None
    function_before = source_text[function_start:function_end]
    function_after = candidate_text[function_start:function_end + len(candidate_text) - len(source_text)]
    source_hunks = _source_hunks(
        function_before,
        function_after,
        function_start_line=source_text.count("\n", 0, function_start) + 1,
        global_name=global_decl.name,
        strategy=strategy,
    )
    payload = {
        "candidate_text": candidate_text,
        "strategy": strategy,
        "global_name": global_decl.name,
        "global_type": global_decl.type_text,
        "alias_name": alias_name,
        "source_hunks": source_hunks,
        "source_diff": _source_diff(source_text, candidate_text),
        "force_phys_targets": {
            str(ig): int(phys) for ig, phys in sorted(force_phys.items())
        },
        "selected_uses": [
            {
                "kind": use.kind,
                "line_no": use.line_no,
                "span_text": use.text,
                "replacement_text": use.replacement.replace(_alias_name(global_decl.name, 0), alias_name),
            }
            for use in selected
        ],
    }
    return (
        Anchor(
            mutator_key=MUTATOR_KEY,
            span=(function_start, function_end),
            payload=payload,
        ),
        candidate_text,
    )


def _declaration_insert_offset(source_text: str, body_open: int) -> int | None:
    line_start = source_text.find("\n", body_open)
    if line_start < 0:
        return None
    cursor = line_start + 1
    insert_offset = cursor
    for match in re.finditer(r".*(?:\n|$)", source_text[cursor:]):
        line_abs_start = cursor + match.start()
        line = match.group(0)
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            insert_offset = line_abs_start + len(line)
            continue
        if re.match(r"PAD_STACK\s*\([^;]*\);", stripped):
            break
        if _is_local_declaration_line(stripped):
            insert_offset = line_abs_start + len(line)
            continue
        break
    return insert_offset


def _safe_bare_global_use(source_text: str, start: int, end: int) -> bool:
    before = _previous_nonspace(source_text, start)
    after_index = _next_nonspace_index(source_text, end)
    after = source_text[after_index:after_index + 2] if after_index is not None else ""
    before_two = source_text[max(0, start - 2):start]
    if before in {"&", "*"}:
        return False
    if before_two in {"++", "--"}:
        return False
    if after.startswith(("++", "--")):
        return False
    if after.startswith("=") and not after.startswith("=="):
        return False
    if after in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="}:
        return False
    if after.startswith(("<<", ">>")):
        tail = source_text[after_index:after_index + 3] if after_index is not None else ""
        if tail in {"<<=", ">>="}:
            return False
    return True


def _previous_nonspace(source_text: str, offset: int) -> str | None:
    cursor = offset - 1
    while cursor >= 0 and source_text[cursor].isspace():
        cursor -= 1
    return source_text[cursor] if cursor >= 0 else None


def _next_nonspace_index(source_text: str, offset: int) -> int | None:
    cursor = offset
    while cursor < len(source_text) and source_text[cursor].isspace():
        cursor += 1
    return cursor if cursor < len(source_text) else None


def _line_start_for_offset(source_text: str, offset: int) -> int:
    return source_text.rfind("\n", 0, offset) + 1


def _line_indent_at(source_text: str, offset: int) -> str:
    cursor = offset
    while cursor < len(source_text) and source_text[cursor] in {" ", "\t"}:
        cursor += 1
    return source_text[offset:cursor]


def _is_local_declaration_line(stripped: str) -> bool:
    if stripped.startswith(("if ", "if(", "for ", "for(", "while ", "while(")):
        return False
    if "=" in stripped and not re.match(
        r"(?:const\s+|volatile\s+|struct\s+)?[A-Za-z_]\w*(?:\s*\*)*\s+"
        r"[A-Za-z_]\w*\s*=",
        stripped,
    ):
        return False
    return re.match(
        r"(?:PAD_STACK\s*\([^;]*\)|"
        r"(?:const\s+|volatile\s+|struct\s+)?[A-Za-z_]\w*(?:\s*\*)*\s+"
        r"[A-Za-z_]\w*(?:\s*\[[^\]]+\])?(?:\s*=\s*[^;]+)?;)",
        stripped,
    ) is not None


def _apply_edits(source_text: str, edits: list[dict[str, Any]]) -> str | None:
    ordered = sorted(edits, key=lambda item: (int(item["start"]), int(item["end"])))
    previous_end = -1
    for edit in ordered:
        start = int(edit["start"])
        end = int(edit["end"])
        span_text = str(edit["span_text"])
        if start < previous_end or end < start or end > len(source_text):
            return None
        if source_text[start:end] != span_text:
            return None
        previous_end = end
    candidate = source_text
    for edit in reversed(ordered):
        start = int(edit["start"])
        end = int(edit["end"])
        candidate = candidate[:start] + str(edit["replacement_text"]) + candidate[end:]
    return candidate


def _source_hunks(
    before: str,
    after: str,
    *,
    function_start_line: int,
    global_name: str,
    strategy: str,
) -> list[dict[str, Any]]:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    hunks: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    for index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
        if tag == "equal":
            continue
        old_lines = [line.rstrip("\n") for line in before_lines[i1:i2]]
        new_lines = [line.rstrip("\n") for line in after_lines[j1:j2]]
        hunks.append({
            "hunk_id": f"global-load-lifetime-{global_name}-{strategy}-{index}",
            "strategy": strategy,
            "global_name": global_name,
            "diff_tag": tag,
            "old_start": function_start_line + i1,
            "old_lines": old_lines,
            "new_start": function_start_line + j1,
            "new_lines": new_lines,
            "unified_diff": "".join(
                difflib.unified_diff(
                    before_lines[max(0, i1 - 2):min(len(before_lines), i2 + 2)],
                    after_lines[max(0, j1 - 2):min(len(after_lines), j2 + 2)],
                    fromfile="source",
                    tofile="candidate",
                    n=2,
                )
            ),
        })
    return hunks


def _source_diff(source_text: str, candidate_text: str) -> str:
    return "".join(
        difflib.unified_diff(
            source_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile="source",
            tofile="candidate",
            n=3,
        )
    )


def _alias_name(global_name: str, ordinal: int) -> str:
    safe = re.sub(r"\W+", "_", global_name).strip("_") or "global"
    return f"global_load_{safe}_{ordinal}"
