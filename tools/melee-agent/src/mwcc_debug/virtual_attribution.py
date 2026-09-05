"""Virtual-register source and interference attribution diagnostics."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

from .colorgraph_parser import find_function, parse_hook_events
from .copy_trace import find_virtual_to_ig
from .parser import Function, Pass, analyze_function, parse_pcdump
from .schedule_explain import (
    _find_global_source_expression,
    _find_source_expression,
)
from .source_field_attribution import (
    SourceFieldContext,
    build_source_field_context,
    infer_global_field_source,
    parse_symbolic_global_address_high_expression,
    parse_symbolic_global_address_low_expression,
    parse_symbolic_global_load_expression,
    source_for_field_offset,
    source_for_global_address_field,
    source_for_global_symbol,
)
from .symbol_bridge import (
    _extract_function_text,
    _parse_params,
    find_var_for_virtual,
    list_bindings,
    walk_local_decls,
)

_LOAD_RE = re.compile(
    r"^[^,]+,\s*(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*"
    r"\(\s*r(?P<base>\d+)\s*\)"
)
_COPY_RE = re.compile(r"^r(?P<dest>\d+)\s*,\s*r(?P<src>\d+)\b")
_LOAD_ADDRESS_RE = re.compile(
    r"^[rf](?P<dest>\d+)\s*,\s*(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))"
    r"\s*\(\s*r(?P<base>\d+)\s*\)"
)
_ADDI_IMMEDIATE_RE = re.compile(
    r"^r(?P<dest>\d+)\s*,\s*r(?P<base>\d+)\s*,\s*"
    r"(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*$"
)

_IMPLICIT_TEMP_OPS = {
    "add",
    "addc",
    "adde",
    "addi",
    "addic",
    "addis",
    "and",
    "andc",
    "andi.",
    "andis.",
    "divw",
    "divwu",
    "extsb",
    "extsh",
    "mulli",
    "mullw",
    "neg",
    "or",
    "ori",
    "oris",
    "rlwinm",
    "rlwimi",
    "slw",
    "sraw",
    "srawi",
    "srw",
    "subf",
    "subfc",
    "subfe",
    "xor",
    "xori",
    "xoris",
}
_COMPARE_TEMP_OPS = {"cmp", "cmpi", "cmpl", "cmpli"}
_FPR_TEMP_OPS = {
    "fabs",
    "fadd",
    "fadds",
    "fcmpo",
    "fcmpu",
    "fctiwz",
    "fdiv",
    "fdivs",
    "fmadd",
    "fmadds",
    "fmr",
    "fmsub",
    "fmsubs",
    "fmul",
    "fmuls",
    "fnabs",
    "fneg",
    "fnmadd",
    "fnmsub",
    "fnmsubs",
    "fres",
    "frsp",
    "frsqrte",
    "fsel",
    "fsub",
    "fsubs",
    "lfd",
    "lfs",
    "stfd",
    "stfs",
}
_FLOATING_SCALAR_TYPES = {"float", "f32", "double", "f64"}
_FPR_SOURCE_EXPR_OPS = {
    "fmul": "*",
    "fmuls": "*",
    "fsub": "-",
    "fsubs": "-",
}
_PLAIN_ASSIGNMENT_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)"
    r"(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)"
    r"[ \t]*=[ \t]*(?P<rhs>[^;\n]+);[ \t]*$"
)
_COMPOUND_FLOAT_SUB_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)"
    r"(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)"
    r"[ \t]*-=[ \t]*(?P<rhs>[^;\n]+);[ \t]*$"
)
_CAST_ONLY_EXPR_RE = re.compile(
    r"^\s*\(\s*"
    r"(?:const\s+|volatile\s+)?"
    r"(?:signed\s+|unsigned\s+)?"
    r"(?:void|char|short|int|long|float|double|"
    r"s8|u8|s16|u16|s32|u32|s64|u64|f32|f64|bool|BOOL)"
    r"(?:\s*\*)*"
    r"\s*\)\s*$"
)
_MWCC_INSPECT_FUNCTION_RE = re.compile(
    r"(?ms)^FUNCTION:\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)\b"
    r"(?P<body>.*?)(?=^=+\s*$\n^FUNCTION:|\Z)"
)
_MWCC_INSPECT_OBJREF_RE = re.compile(
    r"ObjObject\s+@\s+(?P<id>0x[0-9A-Fa-f]+):\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"(?:\s+\(DataType:\s*(?P<data_type>[^,)]*)"
    r"(?:,\s*Type:\s*(?P<type>[^)]*))?\))?"
)
_MWCC_INSPECT_LOCAL_ROW_RE = re.compile(
    r"(?m)^\s*\[\d+\]\s+(?P<id>0x[0-9A-Fa-f]+)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)\b"
)


@dataclass(frozen=True)
class InstructionSite:
    pass_name: str
    block_idx: int
    instr_idx: int
    opcode: str
    operands: str


@dataclass(frozen=True)
class SourceAttribution:
    kind: str
    confidence: str
    name: str | None = None
    type: str | None = None
    source_file: str | None = None
    source_line: int | None = None
    source_col: int | None = None
    expression: str | None = None
    base_virtual: int | None = None
    base_var: str | None = None
    base_confidence: str | None = None
    field_offset: int | None = None
    field_name: str | None = None
    first_def: InstructionSite | None = None
    call_symbol: str | None = None
    copy_chain: tuple[int, ...] = ()
    use_sites: tuple[InstructionSite, ...] = ()
    owner_status: str | None = None
    owner_scope_path: tuple[str, ...] = ()
    objobject_id: str | None = None
    objobject_name: str | None = None
    stack_home_offset: int | None = None


@dataclass(frozen=True)
class InspectObjObject:
    objobject_id: str
    name: str
    type: str | None = None
    data_type: str | None = None


@dataclass(frozen=True)
class InterfererAttribution:
    virtual: int
    assigned_reg: int | None
    source: SourceAttribution | None = None


@dataclass(frozen=True)
class PairInterference:
    virtual: int
    other_virtual: int
    colorgraph_interference: bool
    live_overlap: bool
    same_assigned_reg: bool | None
    reason: str


@dataclass(frozen=True)
class VirtualAttribution:
    virtual: int
    status: str
    class_id: int | None
    ig_idx: int | None
    assigned_reg: int | None
    live_range: tuple[int, int] | None
    live_blocks: tuple[int, ...]
    use_count: int
    first_occurrence: InstructionSite | None
    last_occurrence: InstructionSite | None
    source: SourceAttribution | None
    interferers: tuple[InterfererAttribution, ...]
    note: str | None = None


@dataclass(frozen=True)
class VirtualAttributionReport:
    function: str
    virtuals: tuple[VirtualAttribution, ...]
    pair_interferences: tuple[PairInterference, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _instruction_site_from_occurrence(occurrence) -> InstructionSite | None:
    if occurrence is None:
        return None
    return InstructionSite(
        pass_name=occurrence.pass_name,
        block_idx=occurrence.block_idx,
        instr_idx=occurrence.instr_idx,
        opcode=occurrence.opcode,
        operands=occurrence.operands,
    )


def _mwcc_inspect_function_body(
    inspect_text: str | None,
    function: str,
) -> str:
    if not inspect_text:
        return ""
    for match in _MWCC_INSPECT_FUNCTION_RE.finditer(inspect_text):
        if match.group("name") == function:
            return match.group("body")
    return inspect_text


def _parse_mwcc_inspect_objobjects(
    inspect_text: str | None,
    function: str,
) -> dict[str, InspectObjObject]:
    body = _mwcc_inspect_function_body(inspect_text, function)
    if not body:
        return {}
    by_name: dict[str, InspectObjObject] = {}
    for match in _MWCC_INSPECT_LOCAL_ROW_RE.finditer(body):
        name = match.group("name")
        by_name.setdefault(
            name,
            InspectObjObject(objobject_id=match.group("id"), name=name),
        )
    for match in _MWCC_INSPECT_OBJREF_RE.finditer(body):
        name = match.group("name")
        by_name[name] = InspectObjObject(
            objobject_id=match.group("id"),
            name=name,
            type=(
                match.group("type").strip()
                if match.group("type") is not None else None
            ),
            data_type=(
                match.group("data_type").strip()
                if match.group("data_type") is not None else None
            ),
        )
    return by_name


def _with_owner_objobject(
    source: SourceAttribution | None,
    objobjects_by_name: dict[str, InspectObjObject],
) -> SourceAttribution | None:
    if source is None or source.objobject_id is not None:
        return source
    owner_name = source.name or source.base_var
    if not owner_name:
        return source
    obj = objobjects_by_name.get(owner_name)
    if obj is None:
        return source
    return replace(
        source,
        objobject_id=obj.objobject_id,
        objobject_name=obj.name,
        type=source.type or obj.type,
    )


def _precolor_passes(fn: Function | None) -> tuple[Pass, ...]:
    if fn is None:
        return ()
    out: list[Pass] = []
    for pass_ in fn.passes:
        if pass_.name == "AFTER REGISTER COLORING":
            break
        out.append(pass_)
    return tuple(out)


def _as_passes(passes: Pass | tuple[Pass, ...] | None) -> tuple[Pass, ...]:
    if passes is None:
        return ()
    if isinstance(passes, tuple):
        return passes
    return (passes,)


def _find_first_def_site(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> InstructionSite | None:
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if not instr.regs:
                    continue
                kind, num = instr.regs[0]
                if kind == reg_kind and num == virtual:
                    return InstructionSite(
                        pass_name=pass_.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    )
    return None


def _live_blocks(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> tuple[int, ...]:
    blocks: set[int] = set()
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr in block.instructions:
                if any(kind == reg_kind and num == virtual for kind, num in instr.regs):
                    blocks.add(block.index)
                    break
    return tuple(sorted(blocks))


def _pre_occurrence_sites(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> tuple[InstructionSite, ...]:
    out: list[InstructionSite] = []
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if not any(kind == reg_kind and num == virtual for kind, num in instr.regs):
                    continue
                out.append(InstructionSite(
                    pass_name=pass_.name,
                    block_idx=block.index,
                    instr_idx=instr_idx,
                    opcode=instr.opcode,
                    operands=instr.operands,
                ))
    return tuple(out)


def _bindings_by_virtual(
    source_text: str | None,
    function: str,
    pre_pass: Pass | None,
) -> dict[int, object]:
    if not source_text or pre_pass is None:
        return {}
    try:
        bindings = list_bindings(source_text, function, pre_pass)
    except Exception:
        return {}
    return {
        getattr(binding, "virtual"): binding
        for binding in bindings
        if getattr(binding, "virtual", -1) >= 0
    }


def _source_from_binding(
    binding,
    *,
    source_file: str | None,
) -> SourceAttribution:
    return SourceAttribution(
        kind=str(getattr(binding, "kind", "binding")),
        confidence=str(getattr(binding, "confidence", "best-guess")),
        name=getattr(binding, "var_name", None),
        type=getattr(binding, "type_str", None),
        source_file=source_file,
        source_line=getattr(binding, "decl_line", None),
        expression=getattr(binding, "var_name", None),
        owner_status="source-owned",
        owner_scope_path=tuple(getattr(binding, "scope_path", ()) or ()),
    )


def _is_low_confidence_scalar_field_base(
    *,
    binding: object | None,
    base_confidence: str | None,
    direct: SourceAttribution | None,
) -> bool:
    if direct is None or base_confidence != "low-confidence":
        return False
    expression = direct.expression or ""
    if direct.field_name is not None and "field_at_" not in expression:
        return False
    type_text = getattr(binding, "type_str", None) if binding is not None else None
    if not isinstance(type_text, str):
        return True
    return "*" not in type_text


def _source_from_load(
    site: InstructionSite,
    *,
    bindings_by_virtual: dict[int, object],
    source_text: str | None,
    source_file: str | None,
    field_context: SourceFieldContext | None = None,
    resolve_virtual=None,
) -> SourceAttribution | None:
    if not source_text:
        return None
    match = _LOAD_RE.match(site.operands)
    if match is None:
        return None
    offset = int(match.group("offset"), 0)
    base_virtual = int(match.group("base"))
    base_binding = bindings_by_virtual.get(base_virtual)
    base_var = (
        getattr(base_binding, "var_name", None)
        if base_binding is not None else None
    )
    base_confidence = (
        getattr(base_binding, "confidence", None)
        if base_binding is not None else None
    )
    expression = None
    field_name = None
    line = None
    col = None
    confidence = "field-offset"
    if base_var:
        expression, field_name, line, col, confidence = _find_source_expression(
            source_text,
            base_var=base_var,
            offset=offset,
        )
        if line is None:
            line = getattr(base_binding, "decl_line", None)
    else:
        global_expr = _find_global_source_expression(source_text, offset=offset)
        if global_expr is not None:
            expression, field_name, base_var, line, col = global_expr
            base_confidence = "global-source-expression"
            confidence = "source-expression"
    direct = None
    if expression is not None:
        direct = SourceAttribution(
            kind="field-load",
            confidence=confidence,
            source_file=source_file,
            source_line=line,
            source_col=col,
            expression=expression,
            type=None,
            base_virtual=base_virtual,
            base_var=base_var,
            base_confidence=base_confidence,
            field_offset=offset,
            field_name=field_name,
            first_def=site,
            owner_status="source-owned",
            owner_scope_path=tuple(
                getattr(base_binding, "scope_path", ()) or ()
            ),
        )
    invalid_low_confidence_scalar_base = _is_low_confidence_scalar_field_base(
        binding=base_binding,
        base_confidence=base_confidence,
        direct=direct,
    )
    if (
        direct is not None
        and direct.source_line is not None
        and not invalid_low_confidence_scalar_base
    ):
        return direct

    if field_context is None:
        return None if invalid_low_confidence_scalar_base else direct
    base_source = None
    if resolve_virtual is not None:
        base_source = resolve_virtual(base_virtual)
    if base_source is not None:
        resolved = source_for_field_offset(
            field_context,
            base_expression=base_source.expression or base_source.name,
            base_type=base_source.type,
            offset=offset,
        )
        if resolved is not None:
            return SourceAttribution(
                kind="field-load",
                confidence=(
                    "recursive-source-span"
                    if base_source.confidence != "global-symbol"
                    else "source-span"
                ),
                type=resolved.type,
                source_file=source_file,
                source_line=resolved.source_line,
                source_col=resolved.source_col,
                expression=resolved.expression,
                base_virtual=base_virtual,
                base_var=resolved.base_var or base_source.base_var or base_source.name,
                base_confidence=base_source.confidence,
                field_offset=offset,
                field_name=resolved.field_name,
                first_def=site,
                owner_status="source-owned",
                owner_scope_path=base_source.owner_scope_path,
            )
    resolved = infer_global_field_source(field_context, offset=offset)
    if resolved is not None:
        return SourceAttribution(
            kind="field-load",
            confidence=resolved.confidence,
            type=resolved.type,
            source_file=source_file,
            source_line=resolved.source_line,
            source_col=resolved.source_col,
            expression=resolved.expression,
            base_virtual=base_virtual,
            base_var=resolved.base_var,
            base_confidence="global-source-expression",
            field_offset=offset,
            field_name=resolved.field_name,
            first_def=site,
            owner_status="source-owned",
        )
    return None if invalid_low_confidence_scalar_base else direct


def _source_from_symbolic_global_load(
    site: InstructionSite,
    *,
    field_context: SourceFieldContext | None,
    source_file: str | None,
) -> SourceAttribution | None:
    parsed = parse_symbolic_global_load_expression(
        f"{site.opcode} {site.operands}".strip()
    )
    if parsed is None or field_context is None:
        return None
    _dest_virtual, symbol = parsed
    resolved = source_for_global_symbol(field_context, symbol)
    if resolved is None:
        return None
    return SourceAttribution(
        kind="global-load",
        confidence=resolved.confidence,
        name=symbol,
        type=resolved.type,
        source_file=source_file,
        source_line=resolved.source_line,
        source_col=resolved.source_col,
        expression=resolved.expression,
        base_var=symbol,
        first_def=site,
        owner_status="source-owned",
    )


def _global_address_type(type_name: str | None) -> str | None:
    if not type_name:
        return None
    return f"{type_name}*"


def _is_exact_global_address_source(source: SourceAttribution | None) -> bool:
    return bool(
        source is not None
        and source.name
        and source.confidence in {
            "global-address",
            "global-address-copy-chain",
        }
    )


def _is_global_address_evidence_source(
    source: SourceAttribution | None,
) -> bool:
    return bool(
        source is not None
        and source.name
        and (
            source.kind == "global-address"
            or source.confidence in {
                "global-address",
                "global-address-copy-chain",
                "global-address-provenance-conflict",
                "global-address-unresolved-copy-chain",
            }
        )
    )


def _parse_signed_16bit_immediate(text: str) -> int | None:
    token = text.strip()
    if not token:
        return None
    try:
        value = int(token, 0)
    except ValueError:
        return None
    if value < -0x8000 or value > 0x7FFF:
        return None
    unsigned_hex = token[0] not in {"+", "-"} and token.lower().startswith("0x")
    if unsigned_hex and value >= 0x8000:
        return None
    return value


def _source_from_symbolic_global_address(
    site: InstructionSite,
    *,
    field_context: SourceFieldContext | None,
    source_file: str | None,
    resolve_virtual,
) -> SourceAttribution | None:
    expression = f"{site.opcode} {site.operands}".strip()
    high = parse_symbolic_global_address_high_expression(expression)
    if high is not None and field_context is not None:
        _dest_virtual, symbol = high
        resolved = source_for_global_symbol(field_context, symbol)
        if resolved is None:
            return None
        return SourceAttribution(
            kind="global-address-high",
            confidence="global-address-high",
            name=symbol,
            type=_global_address_type(resolved.type),
            source_file=source_file,
            source_line=resolved.source_line,
            source_col=resolved.source_col,
            expression=f"&{symbol}",
            base_var=symbol,
            first_def=site,
            owner_status="compiler-generated/global-address",
        )

    low = parse_symbolic_global_address_low_expression(expression)
    if low is None or field_context is None:
        return None
    _dest_virtual, base_virtual, symbol = low
    base_source = resolve_virtual(base_virtual)
    exact_pair = (
        base_source is not None
        and base_source.kind == "global-address-high"
        and base_source.confidence == "global-address-high"
        and base_source.name == symbol
    )
    resolved = source_for_global_symbol(field_context, symbol)
    if not exact_pair:
        return SourceAttribution(
            kind="global-address",
            confidence="global-address-provenance-conflict",
            name=symbol,
            type=(
                _global_address_type(resolved.type)
                if resolved is not None else None
            ),
            source_file=source_file,
            source_line=None if resolved is None else resolved.source_line,
            source_col=None if resolved is None else resolved.source_col,
            expression=expression,
            base_virtual=base_virtual,
            base_var=symbol,
            base_confidence=(
                None if base_source is None else base_source.confidence
            ),
            first_def=site,
            owner_status="source-owner-unresolved",
        )
    if resolved is None:
        return None
    return SourceAttribution(
        kind="global-address",
        confidence="global-address",
        name=symbol,
        type=_global_address_type(resolved.type),
        source_file=source_file,
        source_line=resolved.source_line,
        source_col=resolved.source_col,
        expression=f"&{symbol}",
        base_virtual=base_virtual,
        base_var=symbol,
        base_confidence=base_source.confidence,
        first_def=site,
        owner_status="source-owned",
    )


def _unresolved_global_field_address(
    site: InstructionSite,
    *,
    base_source: SourceAttribution,
    base_virtual: int,
    symbol: str,
    source_file: str | None,
    confidence: str,
    field_offset: int | None = None,
) -> SourceAttribution:
    return SourceAttribution(
        kind="global-field-address",
        confidence=confidence,
        name=symbol,
        source_file=source_file,
        expression=f"{site.opcode} {site.operands}".strip(),
        base_virtual=base_virtual,
        base_var=symbol,
        base_confidence=base_source.confidence,
        field_offset=field_offset,
        first_def=site,
        copy_chain=base_source.copy_chain,
        owner_status="source-owner-unresolved",
    )


def _source_from_global_field_address(
    site: InstructionSite,
    *,
    field_context: SourceFieldContext | None,
    source_file: str | None,
    resolve_virtual,
) -> SourceAttribution | None:
    if site.opcode.lower() != "addi" or field_context is None:
        return None
    match = _ADDI_IMMEDIATE_RE.match(site.operands)
    if match is None:
        return None
    base_virtual = int(match.group("base"))
    base_source = resolve_virtual(base_virtual)
    if not _is_global_address_evidence_source(base_source):
        return None
    assert base_source is not None
    symbol = base_source.name
    assert symbol is not None
    offset = _parse_signed_16bit_immediate(match.group("offset"))
    if offset is None:
        return _unresolved_global_field_address(
            site,
            base_source=base_source,
            base_virtual=base_virtual,
            symbol=symbol,
            source_file=source_file,
            confidence="global-field-address-invalid-immediate",
        )
    if not _is_exact_global_address_source(base_source):
        return _unresolved_global_field_address(
            site,
            base_source=base_source,
            base_virtual=base_virtual,
            symbol=symbol,
            source_file=source_file,
            confidence="global-address-provenance-conflict",
            field_offset=offset,
        )
    resolved = source_for_global_address_field(
        field_context,
        symbol=symbol,
        offset=offset,
    )
    if resolved is None:
        return _unresolved_global_field_address(
            site,
            base_source=base_source,
            base_virtual=base_virtual,
            symbol=symbol,
            source_file=source_file,
            confidence="global-field-address-unresolved",
            field_offset=offset,
        )
    source_owned = resolved.source_line is not None
    return SourceAttribution(
        kind="global-field-address",
        confidence=(
            resolved.confidence
            if source_owned
            else "global-field-address-source-span-unresolved"
        ),
        name=symbol,
        type=resolved.type,
        source_file=source_file,
        source_line=resolved.source_line,
        source_col=resolved.source_col,
        expression=resolved.expression,
        base_virtual=base_virtual,
        base_var=resolved.base_var,
        base_confidence=base_source.confidence,
        field_offset=offset,
        field_name=resolved.field_name,
        first_def=site,
        copy_chain=base_source.copy_chain,
        owner_status="source-owned" if source_owned else "source-owner-unresolved",
    )


def _copy_source_from_virtual(
    site: InstructionSite,
    *,
    resolve_virtual,
    source_file: str | None,
) -> SourceAttribution | None:
    match = _COPY_RE.match(site.operands)
    if match is None:
        return None
    src_virtual = int(match.group("src"))
    source = resolve_virtual(src_virtual)
    if source is None or not (source.expression or source.name):
        return None
    if source.confidence == "pcode-first-def":
        return None
    expression = source.expression or source.name
    global_address_copy = _is_exact_global_address_source(source)
    global_address_evidence_copy = _is_global_address_evidence_source(source)
    return SourceAttribution(
        kind="copy/coalesce-source",
        confidence=(
            "global-address-copy-chain"
            if global_address_copy
            else (
                "global-address-unresolved-copy-chain"
                if global_address_evidence_copy else "copy-chain-source-span"
            )
        ),
        name=source.name,
        type=source.type,
        source_file=source.source_file or source_file,
        source_line=source.source_line,
        source_col=source.source_col,
        expression=expression,
        base_virtual=src_virtual,
        base_var=source.base_var or source.name,
        base_confidence=source.confidence,
        field_offset=source.field_offset,
        field_name=source.field_name,
        first_def=site,
        call_symbol=source.call_symbol,
        copy_chain=(int(match.group("dest")), src_virtual, *source.copy_chain),
        use_sites=source.use_sites,
        owner_status=source.owner_status,
        owner_scope_path=source.owner_scope_path,
        objobject_id=source.objobject_id,
        objobject_name=source.objobject_name,
        stack_home_offset=source.stack_home_offset,
    )


def _source_from_first_def(site: InstructionSite, *, source_file: str | None) -> SourceAttribution:
    opcode = site.opcode.lower()
    expression = f"{site.opcode} {site.operands}".strip()
    base_virtual = None
    field_offset = None
    kind = "first-def"

    if opcode == "mr":
        match = _COPY_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("src"))
        kind = "copy/coalesce-product"
    elif opcode in _COMPARE_TEMP_OPS:
        kind = "compare-temp"
    elif opcode.startswith(("lw", "lb", "lha", "lhz", "lf")):
        match = _LOAD_ADDRESS_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("base"))
            field_offset = int(match.group("offset"), 0)
        kind = "load/store-address"
    elif opcode.startswith(("st",)):
        match = _LOAD_ADDRESS_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("base"))
            field_offset = int(match.group("offset"), 0)
        kind = "load/store-address"
    elif opcode in _IMPLICIT_TEMP_OPS:
        kind = "implicit-temp"
    elif opcode in _FPR_TEMP_OPS:
        kind = "fpr-temp"

    return SourceAttribution(
        kind=kind,
        confidence="pcode-first-def",
        source_file=source_file,
        expression=expression,
        base_virtual=base_virtual,
        field_offset=field_offset,
        first_def=site,
        owner_status="compiler-generated/no-owner",
        stack_home_offset=field_offset if base_virtual == 1 else None,
    )


def _source_without_owner(
    *,
    site: InstructionSite | None,
    source_file: str | None,
    reason: str | None = None,
) -> SourceAttribution:
    if site is not None:
        return _source_from_first_def(site, source_file=source_file)
    return SourceAttribution(
        kind="unattributed",
        confidence="no-pcode-owner",
        source_file=source_file,
        expression=reason,
        owner_status="compiler-generated/no-owner",
    )


def _is_floating_scalar_type(type_str: str | None) -> bool:
    if type_str is None:
        return False
    normalized = re.sub(r"\b(?:const|volatile|register|static)\b", "", type_str)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if "*" in normalized or "[" in normalized or "]" in normalized:
        return False
    return normalized in _FLOATING_SCALAR_TYPES


def _floating_decl_types_for_function(
    source_text: str,
    function: str,
) -> dict[str, str]:
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return {}
    params_text, body_text, _start_line = extracted
    names: dict[str, str] = {}
    ambiguous: set[str] = set()
    for decl in [*_parse_params(params_text), *walk_local_decls(body_text)]:
        if not _is_floating_scalar_type(decl.type_str):
            continue
        if decl.name in names:
            ambiguous.add(decl.name)
            continue
        names[decl.name] = decl.type_str
    for name in ambiguous:
        names.pop(name, None)
    return names


def _top_level_operator_present(expression: str, operator: str) -> bool:
    depth = 0
    for idx, ch in enumerate(expression):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == operator and depth == 0:
            if operator == "-" and not _is_binary_top_level_minus(expression, idx):
                continue
            return True
    return False


def _is_binary_top_level_minus(expression: str, idx: int) -> bool:
    before = expression[:idx].rstrip()
    after = expression[idx + 1 :].lstrip()
    if not before or not after:
        return False
    if after.startswith(">"):
        return False
    if before[-1] in "+-*/%&|^!~<>=?:,({[":
        return False
    if _CAST_ONLY_EXPR_RE.fullmatch(before):
        return False
    return True


def _fpr_source_expr_rank(
    site: InstructionSite,
    pre_pass: Pass | tuple[Pass, ...] | None,
) -> int | None:
    operator = _FPR_SOURCE_EXPR_OPS.get(site.opcode.lower())
    if operator is None:
        return None
    rank = 0
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                instr_operator = _FPR_SOURCE_EXPR_OPS.get(instr.opcode.lower())
                if instr_operator != operator or not instr.regs:
                    continue
                kind, num = instr.regs[0]
                if kind != "f" or num < 32:
                    continue
                if _is_conversion_subtract(instr, block.instructions[:instr_idx]):
                    continue
                if (
                    pass_.name == site.pass_name
                    and block.index == site.block_idx
                    and instr_idx == site.instr_idx
                ):
                    return rank
                rank += 1
    return None


def _is_conversion_subtract(instr, previous_instructions) -> bool:
    if instr.opcode.lower() not in {"fsub", "fsubs"} or len(instr.regs) < 3:
        return False
    src_regs = [num for kind, num in instr.regs[1:3] if kind == "f"]
    if len(src_regs) != 2:
        return False

    seen_lfd: set[int] = set()
    for previous in previous_instructions:
        if previous.opcode.lower() != "lfd" or not previous.regs:
            continue
        kind, num = previous.regs[0]
        if kind == "f":
            seen_lfd.add(num)
    return all(num in seen_lfd for num in src_regs)


def _source_from_fpr_expression_assignment(
    site: InstructionSite,
    *,
    function: str,
    pre_pass: Pass | tuple[Pass, ...] | None,
    source_text: str | None,
    source_file: str | None,
) -> SourceAttribution | None:
    if not source_text:
        return None
    operator = _FPR_SOURCE_EXPR_OPS.get(site.opcode.lower())
    if operator is None:
        return None
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return None
    _params_text, body_text, start_line = extracted
    floating_types = _floating_decl_types_for_function(source_text, function)
    if not floating_types:
        return None
    rank = _fpr_source_expr_rank(site, pre_pass)
    if rank is None:
        return None

    candidates: list[tuple[int, str, str, int, int]] = []
    for match in _PLAIN_ASSIGNMENT_RE.finditer(body_text):
        lhs = match.group("lhs")
        if lhs not in floating_types:
            continue
        rhs = match.group("rhs").strip()
        if not _top_level_operator_present(rhs, operator):
            continue
        line = start_line + body_text.count("\n", 0, match.start())
        line_start = body_text.rfind("\n", 0, match.start("rhs")) + 1
        col = match.start("rhs") - line_start + 1
        candidates.append((match.start(), lhs, rhs, line, col))

    if operator == "-":
        for match in _COMPOUND_FLOAT_SUB_RE.finditer(body_text):
            lhs = match.group("lhs")
            if lhs not in floating_types:
                continue
            rhs = match.group("rhs").strip()
            line = start_line + body_text.count("\n", 0, match.start())
            line_start = body_text.rfind("\n", 0, match.start("lhs")) + 1
            col = match.start("lhs") - line_start + 1
            candidates.append((
                match.start(),
                lhs,
                f"{lhs} - {rhs}",
                line,
                col,
            ))

    candidates.sort(key=lambda row: row[0])
    if rank >= len(candidates):
        return None
    _start, name, expression, line, col = candidates[rank]
    return SourceAttribution(
        kind="local",
        confidence="fpr-expression-order",
        name=name,
        type=floating_types.get(name),
        source_file=source_file,
        source_line=line,
        source_col=col,
        expression=expression,
        first_def=site,
        owner_status="source-owned",
    )


def _source_from_call_return_origin(origin, *, source_file: str | None) -> SourceAttribution:
    return SourceAttribution(
        kind="call-return",
        confidence="copy-chain",
        name=origin.assigned_local,
        source_file=origin.source_file or source_file,
        source_line=origin.source_line,
        source_col=origin.source_col,
        expression=origin.expression or f"{origin.call_symbol}(...)",
        first_def=_instruction_site_from_occurrence(origin.call_site),
        call_symbol=origin.call_symbol,
        copy_chain=origin.copy_chain,
        use_sites=tuple(
            site
            for site in (
                _instruction_site_from_occurrence(use_site)
                for use_site in origin.use_sites
            )
            if site is not None
        ),
        owner_status="source-owned",
    )


def _source_for_virtual(
    virtual: int,
    *,
    function: str,
    pre_pass: Pass | tuple[Pass, ...] | None,
    reg_kind: str,
    source_text: str | None,
    source_file: str | None,
    bindings_by_virtual: dict[int, object],
    call_return_origin=None,
    field_context: SourceFieldContext | None = None,
    source_cache: dict[tuple[str, int], SourceAttribution | None] | None = None,
    resolving: set[tuple[str, int]] | None = None,
) -> SourceAttribution | None:
    cache_key = (reg_kind, virtual)
    if source_cache is not None and cache_key in source_cache:
        return source_cache[cache_key]
    if resolving is None:
        resolving = set()
    if cache_key in resolving:
        return None
    resolving.add(cache_key)

    def finish(source: SourceAttribution | None) -> SourceAttribution | None:
        resolving.discard(cache_key)
        if source_cache is not None:
            source_cache[cache_key] = source
        return source

    def resolve_gpr(other_virtual: int) -> SourceAttribution | None:
        return _source_for_virtual(
            other_virtual,
            function=function,
            pre_pass=pre_pass,
            reg_kind="r",
            source_text=source_text,
            source_file=source_file,
            bindings_by_virtual=bindings_by_virtual,
            field_context=field_context,
            source_cache=source_cache,
            resolving=resolving,
        )

    binding = None
    passes = _as_passes(pre_pass)
    binding_pass = passes[-1] if passes else None
    first_def = _find_first_def_site(virtual, pre_pass, reg_kind=reg_kind)
    if reg_kind == "r" and source_text and binding_pass is not None:
        binding = bindings_by_virtual.get(virtual)
        if binding is None:
            try:
                binding = find_var_for_virtual(
                    source_text,
                    function,
                    virtual,
                    binding_pass,
                )
            except Exception:
                binding = None
    if reg_kind == "r" and first_def is not None:
        global_address_source = _source_from_symbolic_global_address(
            first_def,
            field_context=field_context,
            source_file=source_file,
            resolve_virtual=resolve_gpr,
        )
        if global_address_source is not None:
            return finish(global_address_source)
        if first_def.opcode.lower() == "mr":
            global_copy_source = _copy_source_from_virtual(
                first_def,
                resolve_virtual=resolve_gpr,
                source_file=source_file,
            )
            if _is_global_address_evidence_source(global_copy_source):
                return finish(global_copy_source)
        global_field_source = _source_from_global_field_address(
            first_def,
            field_context=field_context,
            source_file=source_file,
            resolve_virtual=resolve_gpr,
        )
        if global_field_source is not None:
            return finish(global_field_source)
    if (
        binding is not None
        and getattr(binding, "confidence", None) != "low-confidence"
    ):
        return finish(_source_from_binding(binding, source_file=source_file))

    if reg_kind == "r" and call_return_origin is not None:
        return finish(_source_from_call_return_origin(
            call_return_origin,
            source_file=source_file,
        ))

    if first_def is None:
        if binding is not None:
            return finish(_source_from_binding(binding, source_file=source_file))
        return finish(None)
    if reg_kind == "f":
        expr_source = _source_from_fpr_expression_assignment(
            first_def,
            function=function,
            pre_pass=pre_pass,
            source_text=source_text,
            source_file=source_file,
        )
        if expr_source is not None:
            return finish(expr_source)
    if reg_kind == "r" and first_def.opcode.lower() == "mr":
        copy_source = _copy_source_from_virtual(
            first_def,
            resolve_virtual=resolve_gpr,
            source_file=source_file,
        )
        if copy_source is not None:
            return finish(copy_source)
    if reg_kind == "r":
        global_source = _source_from_symbolic_global_load(
            first_def,
            field_context=field_context,
            source_file=source_file,
        )
        if global_source is not None:
            return finish(global_source)
    load_source = _source_from_load(
        first_def,
        bindings_by_virtual=bindings_by_virtual,
        source_text=source_text,
        source_file=source_file,
        field_context=field_context,
        resolve_virtual=resolve_gpr,
    )
    if load_source is not None:
        return finish(load_source)
    pcode_source = _source_from_first_def(first_def, source_file=source_file)
    if binding is not None and pcode_source is None:
        return finish(_source_from_binding(binding, source_file=source_file))
    return finish(pcode_source)


def list_pcode_virtuals(
    pcdump_text: str,
    function: str,
) -> tuple[int, ...]:
    """Return all GPR virtuals observed in the function's pre-coloring pcode."""
    fns = parse_pcdump(pcdump_text, function=function)
    fn: Function | None = fns[0] if fns else None
    if fn is None:
        return ()
    virtuals: set[int] = set()
    for pass_ in _precolor_passes(fn):
        for block in pass_.blocks:
            for instr in block.instructions:
                for kind, num in instr.regs:
                    if kind == "r" and num >= 32:
                        virtuals.add(num)
    return tuple(sorted(virtuals))


def _decision_for(events, class_id: int | None, ig_idx: int | None):
    if events is None or ig_idx is None:
        return None
    for section in events.colorgraph_sections:
        if class_id is not None and section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.ig_idx == ig_idx:
                return decision
    return None


def _reg_kind_for_class(class_id: int | None) -> str:
    return "f" if class_id == 1 else "r"


def _reg_kind_for_requested_class(reg_class: str | None) -> str:
    normalized = (reg_class or "gpr").strip().lower()
    if normalized in {"f", "fpr", "float", "floating", "1"}:
        return "f"
    return "r"


def _decision_interferers(
    decision,
    *,
    by_virtual: dict[int, VirtualAttribution],
) -> tuple[InterfererAttribution, ...]:
    if decision is None:
        return ()
    out: list[InterfererAttribution] = []
    for other_virtual, assigned_reg in decision.interferers:
        other = by_virtual.get(other_virtual)
        out.append(InterfererAttribution(
            virtual=other_virtual,
            assigned_reg=assigned_reg,
            source=None if other is None else other.source,
        ))
    return tuple(out)


def _ranges_overlap(
    a: tuple[int, int] | None,
    b: tuple[int, int] | None,
) -> bool:
    if a is None or b is None:
        return False
    return max(a[0], b[0]) <= min(a[1], b[1])


def _pair_reason(
    left: VirtualAttribution | None,
    right: VirtualAttribution | None,
    *,
    colorgraph_interference: bool,
    live_overlap: bool,
) -> tuple[bool | None, str]:
    if left is None or right is None:
        return None, "one or both virtuals were not found in the report"
    same_assigned = None
    if left.assigned_reg is not None and right.assigned_reg is not None:
        same_assigned = left.assigned_reg == right.assigned_reg

    parts: list[str] = []
    if colorgraph_interference:
        parts.append("colorgraph lists the pair as interferers")
    if live_overlap:
        parts.append(
            "live ranges overlap "
            f"r{left.virtual}={left.live_range} and "
            f"r{right.virtual}={right.live_range}"
        )
    if not parts:
        return same_assigned, "no parsed colorgraph or live-range interference"
    if same_assigned is True:
        return same_assigned, (
            "not forced apart: both virtuals are assigned "
            f"r{left.assigned_reg}; " + "; ".join(parts)
        )
    phys = []
    if left.assigned_reg is not None:
        phys.append(f"r{left.virtual}->r{left.assigned_reg}")
    if right.assigned_reg is not None:
        phys.append(f"r{right.virtual}->r{right.assigned_reg}")
    phys_suffix = f"; assigned {' '.join(phys)}" if phys else ""
    return same_assigned, "cannot coalesce: " + "; ".join(parts) + phys_suffix


def _pair_interference(
    pair: tuple[int, int],
    *,
    by_virtual: dict[int, VirtualAttribution],
    decisions_by_virtual: dict[int, object],
) -> PairInterference:
    left_virtual, right_virtual = pair
    left = by_virtual.get(left_virtual)
    right = by_virtual.get(right_virtual)
    left_decision = decisions_by_virtual.get(left_virtual)
    right_decision = decisions_by_virtual.get(right_virtual)
    left_has_right = (
        left_decision is not None
        and any(v == right_virtual for v, _reg in left_decision.interferers)
    )
    right_has_left = (
        right_decision is not None
        and any(v == left_virtual for v, _reg in right_decision.interferers)
    )
    colorgraph_interference = left_has_right or right_has_left
    live_overlap = _ranges_overlap(
        None if left is None else left.live_range,
        None if right is None else right.live_range,
    )
    same_assigned, reason = _pair_reason(
        left,
        right,
        colorgraph_interference=colorgraph_interference,
        live_overlap=live_overlap,
    )
    return PairInterference(
        virtual=left_virtual,
        other_virtual=right_virtual,
        colorgraph_interference=colorgraph_interference,
        live_overlap=live_overlap,
        same_assigned_reg=same_assigned,
        reason=reason,
    )


def explain_virtuals(
    pcdump_text: str,
    function: str,
    *,
    virtuals: list[int] | tuple[int, ...],
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    source_text: str | None = None,
    source_file: str | None = None,
    reg_class: str | None = "gpr",
    enable_field_context: bool = True,
    inspect_text: str | None = None,
) -> VirtualAttributionReport:
    """Explain source provenance, pcdump live blocks, and pair interference."""
    requested: list[int] = []
    seen: set[int] = set()
    for virtual in list(virtuals) + [v for pair in pairs for v in pair]:
        if virtual in seen:
            continue
        seen.add(virtual)
        requested.append(virtual)
    if not requested:
        raise ValueError("at least one virtual or pair is required")

    fns = parse_pcdump(pcdump_text, function=function)
    fn: Function | None = fns[0] if fns else None
    pre_pass = None if fn is None else fn.last_precolor_pass()
    pre_passes = _precolor_passes(fn)
    infos = (
        {}
        if fn is None
        else {(info.reg_kind, info.virtual): info for info in analyze_function(fn)}
    )
    bindings = _bindings_by_virtual(source_text, function, pre_pass)
    field_context = (
        build_source_field_context(
            source_text,
            function=function,
            source_file=source_file,
        )
        if source_text and enable_field_context else None
    )
    source_cache: dict[tuple[str, int], SourceAttribution | None] = {}
    events = find_function(parse_hook_events(pcdump_text), function)
    objobjects_by_name = _parse_mwcc_inspect_objobjects(inspect_text, function)

    provisional: list[VirtualAttribution] = []
    decisions_by_virtual: dict[int, object] = {}
    for virtual in requested:
        mapping = find_virtual_to_ig(
            pcdump_text,
            function,
            virtual,
            reg_class=reg_class,
            source_text=source_text,
            source_file=source_file,
        )
        reg_kind = (
            _reg_kind_for_class(mapping.class_id)
            if mapping.class_id is not None
            else _reg_kind_for_requested_class(reg_class)
        )
        info = infos.get((reg_kind, virtual))
        live_range = None if info is None else (info.first_use, info.last_use)
        assigned_reg = mapping.assigned_reg
        if (
            assigned_reg is None
            and info is not None
            and mapping.status == "pcode-only"
            and reg_kind == "f"
        ):
            assigned_reg = info.physical
        pre_occurrences = _pre_occurrence_sites(
            virtual,
            pre_passes,
            reg_kind=reg_kind,
        )
        first_occurrence = pre_occurrences[0] if pre_occurrences else (
            _instruction_site_from_occurrence(mapping.first_occurrence)
        )
        last_occurrence = pre_occurrences[-1] if pre_occurrences else (
            _instruction_site_from_occurrence(mapping.last_occurrence)
        )
        source = _source_for_virtual(
            virtual,
            function=function,
            pre_pass=pre_passes,
            reg_kind=reg_kind,
            source_text=source_text,
            source_file=source_file,
            bindings_by_virtual=bindings,
            call_return_origin=mapping.call_return_origin,
            field_context=field_context,
            source_cache=source_cache,
        )
        source = _with_owner_objobject(source, objobjects_by_name)
        if source is None and mapping.status in {
            "colorgraph",
            "simplify-only",
            "pcode-only",
        }:
            source = _source_without_owner(
                site=first_occurrence,
                source_file=source_file,
                reason=mapping.note,
            )
        decision = _decision_for(events, mapping.class_id, mapping.ig_idx)
        if decision is not None:
            decisions_by_virtual[virtual] = decision
        provisional.append(VirtualAttribution(
            virtual=virtual,
            status=mapping.status,
            class_id=mapping.class_id,
            ig_idx=mapping.ig_idx,
            assigned_reg=assigned_reg,
            live_range=live_range,
            live_blocks=_live_blocks(virtual, pre_passes, reg_kind=reg_kind),
            use_count=len(pre_occurrences) if info is None else info.use_count,
            first_occurrence=first_occurrence,
            last_occurrence=last_occurrence,
            source=source,
            interferers=(),
            note=mapping.note,
        ))

    by_virtual = {entry.virtual: entry for entry in provisional}
    with_interferers: list[VirtualAttribution] = []
    for entry in provisional:
        decision = decisions_by_virtual.get(entry.virtual)
        with_interferers.append(VirtualAttribution(
            virtual=entry.virtual,
            status=entry.status,
            class_id=entry.class_id,
            ig_idx=entry.ig_idx,
            assigned_reg=entry.assigned_reg,
            live_range=entry.live_range,
            live_blocks=entry.live_blocks,
            use_count=entry.use_count,
            first_occurrence=entry.first_occurrence,
            last_occurrence=entry.last_occurrence,
            source=entry.source,
            interferers=_decision_interferers(decision, by_virtual=by_virtual),
            note=entry.note,
        ))
    by_virtual = {entry.virtual: entry for entry in with_interferers}
    pair_reports = tuple(
        _pair_interference(
            pair,
            by_virtual=by_virtual,
            decisions_by_virtual=decisions_by_virtual,
        )
        for pair in pairs
    )
    return VirtualAttributionReport(
        function=function,
        virtuals=tuple(with_interferers),
        pair_interferences=pair_reports,
    )


def render_virtual_attribution_text(report: VirtualAttributionReport) -> str:
    lines: list[str] = [f"explain-virtual - {report.function}"]
    for entry in report.virtuals:
        phys = "?" if entry.assigned_reg is None else f"r{entry.assigned_reg}"
        live = (
            "?"
            if entry.live_range is None
            else f"{entry.live_range[0]}..{entry.live_range[1]}"
        )
        blocks = (
            "-"
            if not entry.live_blocks
            else ",".join(f"B{block}" for block in entry.live_blocks)
        )
        lines.append(
            f"- r{entry.virtual}: status={entry.status} "
            f"ig={entry.ig_idx if entry.ig_idx is not None else '?'} "
            f"phys={phys} live={live} blocks={blocks}"
        )
        if entry.note:
            lines.append(f"  note:   {entry.note}")
        if entry.source is not None:
            source = entry.source
            loc = ""
            if source.source_file and source.source_line is not None:
                loc = f" {source.source_file}:{source.source_line}"
                if source.source_col is not None:
                    loc += f":{source.source_col}"
            expr = source.expression or source.name or "?"
            lines.append(
                f"  source:{loc} {expr} "
                f"({source.kind}, {source.confidence})"
            )
            if source.owner_status:
                scope = ""
                if source.owner_scope_path:
                    try:
                        from .scope_path import format_for_display
                        scope = f" scope={format_for_display(source.owner_scope_path)}"
                    except Exception:
                        scope = " scope=" + "/".join(source.owner_scope_path)
                lines.append(f"  owner: {source.owner_status}{scope}")
            if source.objobject_id:
                name = source.objobject_name or source.name or source.base_var or "?"
                lines.append(f"  obj:    {name} @ {source.objobject_id}")
            if source.stack_home_offset is not None:
                lines.append(f"  stack:  r1+0x{source.stack_home_offset:X}")
            if source.base_virtual is not None:
                base = source.base_var or "?"
                lines.append(
                    f"  base:   r{source.base_virtual} {base} "
                    f"offset=0x{source.field_offset:X}"
                    if source.field_offset is not None
                    else f"  base:   r{source.base_virtual} {base}"
                )
            if source.first_def is not None:
                site = source.first_def
                lines.append(
                    "  first:  "
                    f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                    f"{site.opcode} {site.operands}"
                )
            if source.copy_chain:
                chain = " <- ".join(f"r{reg}" for reg in source.copy_chain)
                lines.append(f"  chain:  {chain}")
            if source.use_sites:
                for site in source.use_sites[:3]:
                    lines.append(
                        "  use:    "
                        f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                        f"{site.opcode} {site.operands}"
                    )
        if entry.interferers:
            rendered = []
            for interferer in entry.interferers:
                assigned = (
                    "?"
                    if interferer.assigned_reg is None
                    else f"r{interferer.assigned_reg}"
                )
                rendered.append(f"r{interferer.virtual}->{assigned}")
            lines.append(f"  cg-int: {', '.join(rendered)}")
    if report.pair_interferences:
        lines.append("Pairs:")
        for pair in report.pair_interferences:
            lines.append(
                f"- r{pair.virtual}/r{pair.other_virtual}: {pair.reason}"
            )
    return "\n".join(lines)
