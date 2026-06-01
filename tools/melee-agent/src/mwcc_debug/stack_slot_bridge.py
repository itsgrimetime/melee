"""Bridge checkdiff stack-slot mismatches to MWCC allocator roots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .colorgraph_parser import find_function, parse_hook_events
from .copy_trace import find_virtual_to_ig
from .parser import Function, Pass, parse_pcdump
from .virtual_attribution import explain_virtuals

_STACK_R1_RE = re.compile(
    r"(?<![@\w])(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_STACK_R1_ANY_RE = re.compile(
    r"(?P<slot>@?[A-Za-z0-9_]\w*(?:[+-]\d+)?)\s*\(\s*r1\s*\)"
)
_REG_RE = re.compile(r"\b(?P<kind>[rf])(?P<num>\d+)\b")
_CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")

_FINAL_PASS_PREFERENCE = (
    "FINAL CODE AFTER INSTRUCTION SCHEDULING",
    "AFTER PEEPHOLE OPTIMIZATION",
    "AFTER MERGING EPILOGUE, PROLOGUE",
    "AFTER GENERATING EPILOGUE, PROLOGUE",
)

_STACK_OPS = {
    "lbz",
    "lha",
    "lhz",
    "lwz",
    "stb",
    "sth",
    "stw",
    "lfd",
    "lfs",
    "stfd",
    "stfs",
}

_SOURCE_CALL_HINTS = {
    "sqrtf",
    "sqrtf__Ff",
    "lbVector_sqrtf_accurate",
}


@dataclass(frozen=True)
class StackSlotSite:
    pass_name: str
    block_idx: int
    instr_idx: int
    opcode: str
    operands: str
    offset: int
    reg_kind: str
    virtual: int
    site_kind: str = "precolor-stack-site"

    @property
    def virtual_token(self) -> str:
        return f"{self.reg_kind}{self.virtual}"

    def evidence(self) -> str:
        return (
            f"{self.pass_name} B{self.block_idx}:{self.instr_idx} "
            f"{self.opcode} {self.operands}"
        )


def explain_stack_slot_localizer(
    pcdump_text: str,
    function: str,
    localizer: dict[str, Any],
    *,
    source_text: str | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    """Map stack-slot localizer mismatches to likely pcode/IG roots.

    The checkdiff localizer knows the concrete r1 offset delta, but not which
    compiler temporary owns the slot. This helper reads the current build's
    pcdump, finds the pre-coloring stack reference at the current offset, and
    joins that virtual with simplify/colorgraph/coalescing facts.
    """
    fns = parse_pcdump(pcdump_text, function=function)
    if not fns:
        return {
            "status": "function-not-found",
            "function": function,
            "candidate_count": 0,
            "candidates": [],
            "note": f"{function!r} not found in pcdump",
        }

    fn = fns[0]
    events = find_function(parse_hook_events(pcdump_text), function)
    pre_pass = _select_precolor_pass(fn)
    final_pass = _select_final_pass(fn)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str, int]] = set()

    for mismatch in localizer.get("mismatches") or []:
        opcode = str(mismatch.get("opcode") or "").lower()
        try:
            current_offset = int(mismatch["current_offset"])
        except (KeyError, TypeError, ValueError):
            continue
        sites = _find_precolor_stack_sites(pre_pass, opcode, current_offset)
        if not sites and final_pass is not None:
            sites = _infer_sites_from_final_pass(
                fn,
                final_pass,
                events,
                opcode,
                current_offset,
            )
        for site in sites:
            key = (site.offset, site.virtual, site.reg_kind, current_offset)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                _candidate_for_site(
                    pcdump_text,
                    function,
                    site,
                    mismatch,
                    fn=fn,
                    events=events,
                    source_text=source_text,
                    source_file=source_file,
                )
            )

    return {
        "status": "ok" if candidates else "no-candidates",
        "function": function,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def render_stack_slot_bridge_summary(report: dict[str, Any]) -> str | None:
    candidates = report.get("candidates") or []
    if not candidates:
        return None
    first = candidates[0]
    source = first.get("nearest_source_expression") or {}
    source_text = source.get("expression")
    source_suffix = f", source {source_text}" if source_text else ""
    assigned = first.get("assigned_reg")
    assigned_suffix = f", assigned {assigned}" if assigned else ""
    spilled = first.get("simplify", {}).get("spilled")
    spill_text = "spill " if spilled else ""
    return (
        "pcdump bridge: likely class "
        f"{first.get('register_class')} {spill_text}root "
        f"{first.get('spill_root')}{assigned_suffix}{source_suffix}"
    )


def _candidate_for_site(
    pcdump_text: str,
    function: str,
    site: StackSlotSite,
    mismatch: dict[str, Any],
    *,
    fn: Function,
    events,
    source_text: str | None,
    source_file: str | None,
) -> dict[str, Any]:
    reg_class = _class_for_reg_kind(site.reg_kind)
    class_label = "fpr" if reg_class == 1 else "gpr"
    mapping = find_virtual_to_ig(
        pcdump_text,
        function,
        site.virtual,
        reg_class=class_label,
        source_text=source_text,
        source_file=source_file,
    )
    simplify = _simplify_details(events, reg_class, site.virtual)
    assigned_reg = (
        None
        if mapping.assigned_reg is None
        else f"{site.reg_kind}{mapping.assigned_reg}"
    )
    source = _nearest_source_expression(
        pcdump_text,
        function,
        site.virtual,
        reg_class=class_label,
        source_text=source_text,
        source_file=source_file,
    )
    candidate = {
        "mismatch": mismatch,
        "opcode": site.opcode,
        "current_offset": site.offset,
        "expected_offset": mismatch.get("expected_offset"),
        "delta": mismatch.get("delta"),
        "register_class": reg_class,
        "virtual": site.virtual,
        "virtual_token": site.virtual_token,
        "site_kind": site.site_kind,
        "spill_root": f"r{mapping.ig_idx if mapping.ig_idx is not None else site.virtual}",
        "ig_idx": mapping.ig_idx,
        "mapping_status": mapping.status,
        "assigned_reg": assigned_reg,
        "simplify": simplify,
        "coalesced_aliases": _coalesced_aliases(events, reg_class, site.virtual),
        "natural_coalesce_aliases": _natural_coalesce_aliases(
            events,
            reg_class,
            site.virtual,
        ),
        "stack_home_order": _stack_home_order(fn, events, reg_class),
        "nearest_source_expression": source,
        "evidence": [site.evidence()],
    }
    if mapping.note:
        candidate["note"] = mapping.note
    return candidate


def _select_final_pass(fn: Function) -> Pass | None:
    by_name = {pass_.name: pass_ for pass_ in fn.passes}
    for name in _FINAL_PASS_PREFERENCE:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _select_precolor_pass(fn: Function) -> Pass | None:
    by_name = {pass_.name: pass_ for pass_ in fn.passes}
    if "BEFORE REGISTER COLORING" in by_name:
        return by_name["BEFORE REGISTER COLORING"]
    if "AFTER INSTRUCTION SCHEDULING" in by_name:
        return by_name["AFTER INSTRUCTION SCHEDULING"]
    return fn.last_precolor_pass()


def _find_precolor_stack_sites(
    pass_: Pass | None,
    opcode: str,
    offset: int,
) -> list[StackSlotSite]:
    if pass_ is None:
        return []
    return [
        site
        for site in _stack_sites_in_pass(pass_)
        if site.opcode == opcode and site.offset == offset and site.virtual >= 32
    ]


def _infer_sites_from_final_pass(
    fn: Function,
    final_pass: Pass,
    events,
    opcode: str,
    offset: int,
) -> list[StackSlotSite]:
    """Fallback for dumps where the selected precolor pass lacks the stack op."""
    final_sites = [
        site
        for site in _stack_sites_in_pass(final_pass)
        if site.opcode == opcode and site.offset == offset
    ]
    if not final_sites:
        final_sites = _symbolic_stack_sites_in_pass(
            final_pass,
            opcode,
            assumed_offset=offset,
        )
    if not final_sites:
        return []
    pre_pass = _select_precolor_pass(fn)
    if pre_pass is None:
        return []
    pre_sites = [
        site
        for site in _stack_sites_in_pass(pre_pass)
        if site.opcode == opcode and site.offset == offset and site.virtual >= 32
    ]
    if pre_sites:
        return pre_sites

    inferred: list[StackSlotSite] = []
    for site in final_sites:
        class_id = _class_for_reg_kind(site.reg_kind)
        virtuals = _virtuals_assigned_to_phys(events, class_id, site.virtual)
        for virtual in virtuals:
            inferred.append(StackSlotSite(
                pass_name=site.pass_name,
                block_idx=site.block_idx,
                instr_idx=site.instr_idx,
                opcode=site.opcode,
                operands=site.operands,
                offset=site.offset,
                reg_kind=site.reg_kind,
                virtual=virtual,
                site_kind="final-only-stack-home",
            ))
    return inferred


def _virtuals_assigned_to_phys(events, class_id: int, phys: int) -> list[int]:
    if events is None:
        return []
    out: list[int] = []
    for section in events.colorgraph_sections:
        if section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.assigned_reg == phys:
                out.append(decision.ig_idx)
    spilled = _spilled_virtuals(events, class_id)
    spilled_out = [virtual for virtual in out if virtual in spilled]
    return spilled_out or out


def _spilled_virtuals(events, class_id: int) -> set[int]:
    if events is None:
        return set()
    return {
        entry.ig_idx
        for section in events.simplify_sections
        if section.class_id == class_id
        for entry in section.entries
        if entry.spilled
    }


def _symbolic_stack_sites_in_pass(
    pass_: Pass,
    opcode: str,
    *,
    assumed_offset: int,
) -> list[StackSlotSite]:
    sites: list[StackSlotSite] = []
    volatile_sites: list[StackSlotSite] = []
    for block in pass_.blocks:
        for instr_idx, instr in enumerate(block.instructions):
            if instr.opcode.lower() != opcode:
                continue
            if _stack_offset(instr.operands) is not None:
                continue
            if _stack_slot_token(instr.operands) is None:
                continue
            reg = _first_register(instr.operands)
            if reg is None:
                continue
            kind, num = reg
            site = StackSlotSite(
                pass_name=pass_.name,
                block_idx=block.index,
                instr_idx=instr_idx,
                opcode=opcode,
                operands=instr.operands,
                offset=assumed_offset,
                reg_kind=kind,
                virtual=num,
                site_kind="final-symbolic-stack-home",
            )
            sites.append(site)
            if "fIsVolatile" in instr.annotations:
                volatile_sites.append(site)
    return volatile_sites or sites


def _stack_sites_in_pass(pass_: Pass) -> list[StackSlotSite]:
    out: list[StackSlotSite] = []
    for block in pass_.blocks:
        for instr_idx, instr in enumerate(block.instructions):
            opcode = instr.opcode.lower()
            if opcode not in _STACK_OPS:
                continue
            offset = _stack_offset(instr.operands)
            if offset is None:
                continue
            reg = _first_register(instr.operands)
            if reg is None:
                continue
            kind, num = reg
            out.append(
                StackSlotSite(
                    pass_name=pass_.name,
                    block_idx=block.index,
                    instr_idx=instr_idx,
                    opcode=opcode,
                    operands=instr.operands,
                    offset=offset,
                    reg_kind=kind,
                    virtual=num,
                )
            )
    return out


def _stack_offset(operands: str) -> int | None:
    match = _STACK_R1_RE.search(operands)
    if match is None:
        return None
    try:
        return int(match.group("offset"), 0)
    except ValueError:
        return None


def _stack_slot_token(operands: str) -> str | None:
    match = _STACK_R1_ANY_RE.search(operands)
    if match is None:
        return None
    token = match.group("slot")
    if re.fullmatch(r"[-+]?(?:0x[0-9A-Fa-f]+|\d+)", token):
        return None
    return token


def _first_register(operands: str) -> tuple[str, int] | None:
    match = _REG_RE.search(operands)
    if match is None:
        return None
    return match.group("kind"), int(match.group("num"))


def _class_for_reg_kind(reg_kind: str) -> int:
    return 1 if reg_kind == "f" else 0


def _simplify_details(events, class_id: int, virtual: int) -> dict[str, Any]:
    if events is None:
        return {}
    for section in events.simplify_sections:
        if section.class_id != class_id:
            continue
        for entry in section.entries:
            if entry.ig_idx == virtual:
                return {
                    "iter": entry.iter_idx,
                    "degree": entry.degree,
                    "array_size": entry.array_size,
                    "flags": entry.flags,
                    "spilled": entry.spilled,
                }
    return {}


def _coalesced_aliases(events, class_id: int, virtual: int) -> list[dict[str, Any]]:
    if events is None:
        return []
    aliases: list[dict[str, Any]] = []
    for section in events.coalesced_alias_sections:
        if section.class_id != class_id:
            continue
        for alias, root, root_phys in section.aliases:
            if alias == virtual or root == virtual:
                kind = "f" if class_id == 1 else "r"
                aliases.append({
                    "alias": alias,
                    "root": root,
                    "root_phys": f"{kind}{root_phys}",
                })
    return aliases


def _natural_coalesce_aliases(
    events,
    class_id: int,
    virtual: int,
) -> list[dict[str, int]]:
    if events is None:
        return []
    aliases: list[dict[str, int]] = []
    for section in events.coalesce_sections:
        if section.class_id != class_id:
            continue
        for alias, root in section.mappings:
            if alias == virtual or root == virtual:
                aliases.append({"alias": alias, "root": root})
    return aliases


def _stack_home_order(fn: Function, events, class_id: int) -> list[dict[str, Any]]:
    pre_pass = _select_precolor_pass(fn)
    if pre_pass is None:
        return []
    reg_kind = "f" if class_id == 1 else "r"
    roots = _alias_root_map(events, class_id)
    grouped: dict[tuple[int, int, str], set[str]] = {}
    for site in _stack_sites_in_pass(pre_pass):
        if site.reg_kind != reg_kind or site.virtual < 32:
            continue
        virtual = roots.get(site.virtual, site.virtual)
        token = f"{reg_kind}{virtual}"
        grouped.setdefault((site.offset, virtual, token), set()).add(site.opcode)
    return [
        {
            "offset": offset,
            "virtual": virtual,
            "virtual_token": token,
            "opcodes": sorted(opcodes),
        }
        for (offset, virtual, token), opcodes in sorted(grouped.items())
    ]


def _alias_root_map(events, class_id: int) -> dict[int, int]:
    roots: dict[int, int] = {}
    if events is None:
        return roots
    for section in events.coalesce_sections:
        if section.class_id != class_id:
            continue
        for alias, root in section.mappings:
            roots[alias] = root
    for section in events.coalesced_alias_sections:
        if section.class_id != class_id:
            continue
        for alias, root, _root_phys in section.aliases:
            roots[alias] = root
    return roots


def _nearest_source_expression(
    pcdump_text: str,
    function: str,
    virtual: int,
    *,
    reg_class: str,
    source_text: str | None,
    source_file: str | None,
) -> dict[str, Any] | None:
    source_call = _find_source_call_expression(
        source_text,
        function=function,
        source_file=source_file,
    )
    if source_call is not None:
        return source_call
    try:
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=[virtual],
            source_text=source_text,
            source_file=source_file,
            reg_class=reg_class,
        )
    except Exception:
        return None
    if not report.virtuals:
        return None
    source = report.virtuals[0].source
    if source is None:
        return None
    expression = source.expression or source.name
    if not expression:
        return None
    return {
        "expression": expression,
        "confidence": source.confidence,
        "source_file": source.source_file,
        "source_line": source.source_line,
        "source_col": source.source_col,
    }


def _find_source_call_expression(
    source_text: str | None,
    *,
    function: str,
    source_file: str | None,
) -> dict[str, Any] | None:
    if not source_text:
        return None
    for line_no, line in _function_source_lines(source_text, function):
        for match in _CALL_RE.finditer(line):
            name = match.group("name")
            if name not in _SOURCE_CALL_HINTS and not name.endswith("sqrtf"):
                continue
            open_paren = line.find("(", match.start())
            close_paren = _find_matching_paren(line, open_paren)
            if close_paren is None:
                continue
            return {
                "expression": line[match.start():close_paren + 1].strip(),
                "confidence": "source-call-heuristic",
                "source_file": source_file,
                "source_line": line_no,
                "source_col": match.start() + 1,
            }
    return None


def _function_source_lines(source_text: str, function: str) -> list[tuple[int, str]]:
    lines = source_text.splitlines()
    match = re.search(rf"\b{re.escape(function)}\s*\(", source_text)
    if match is None:
        return list(enumerate(lines, start=1))
    open_brace = source_text.find("{", match.end())
    if open_brace < 0:
        return list(enumerate(lines, start=1))
    close_brace = _find_matching_brace(source_text, open_brace)
    if close_brace is None:
        return list(enumerate(lines, start=1))
    start_line = source_text.count("\n", 0, open_brace + 1) + 1
    body = source_text[open_brace + 1:close_brace]
    return list(enumerate(body.splitlines(), start=start_line))


def _find_matching_brace(text: str, open_idx: int) -> int | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "{":
        return None
    depth = 0
    for idx in range(open_idx, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _find_matching_paren(text: str, open_idx: int) -> int | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "(":
        return None
    depth = 0
    for idx in range(open_idx, len(text)):
        char = text[idx]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return idx
    return None
