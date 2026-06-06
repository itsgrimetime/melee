"""Explain observed scheduler windows for force-schedule targets."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace

from .asm_windows import (
    AsmWindowCandidate,
    AsmWindowResult,
    explain_code_offset_window,
    is_memory_load_opcode,
)
from .parser import Function, Instruction, Pass, parse_pcdump


@dataclass(frozen=True)
class ScheduleRule:
    opcode: str
    before_offset: int
    after_offset: int
    raw: str


@dataclass(frozen=True)
class ScheduleSource:
    ir_node_id: str | None
    ir_virtual: int | None
    base_virtual: int | None
    base_var: str | None
    base_confidence: str | None
    source_file: str | None
    source_line: int | None
    source_col: int | None
    expression: str | None
    field_offset: int | None
    field_name: str | None
    confidence: str


@dataclass(frozen=True)
class ScheduleSourceReshape:
    rank: int
    kind: str
    title: str
    mechanically_applicable: bool
    target_expression: str | None
    observed_expression: str | None
    source_file: str | None
    source_line: int | None
    source_col: int | None
    patch_hint: str
    rationale: str


@dataclass(frozen=True)
class ScheduleCandidate:
    role: str
    opcode: str
    operands: str
    offset: int | None
    base: str | None
    window_rank: int
    block: int
    index: int
    source: ScheduleSource | None = None
    code_offset: int | None = None
    instruction_class: str | None = None


@dataclass(frozen=True)
class ScheduleDecision:
    rule: ScheduleRule
    status: str
    heuristic_verdict: str
    window_gap: int | None
    rationale: str
    block: int | None = None
    candidates: tuple[ScheduleCandidate, ...] = ()
    window_kind: str | None = None
    forceability: str | None = None
    source_shape_verdict: str | None = None
    source_reshapes: tuple[ScheduleSourceReshape, ...] = ()


@dataclass(frozen=True)
class ScheduleExplainReport:
    function: str
    pass_name: str | None
    decisions: tuple[ScheduleDecision, ...]


@dataclass(frozen=True)
class ScheduleDiffFinding:
    step: int
    rule: ScheduleRule
    real_status: str
    forced_status: str
    real_heuristic_verdict: str
    forced_heuristic_verdict: str
    real_window_gap: int | None
    forced_window_gap: int | None
    margin: int | None
    real_pick: ScheduleCandidate | None
    forced_pick: ScheduleCandidate | None
    rationale: str


@dataclass(frozen=True)
class ScheduleDiffReport:
    function: str
    real_pass_name: str | None
    forced_pass_name: str | None
    finding: ScheduleDiffFinding | None
    real: ScheduleExplainReport
    forced: ScheduleExplainReport


_RULE_RE = re.compile(
    r"^(?P<opcode>[A-Za-z0-9_.]+):(?P<before>[-+]?0x[0-9A-Fa-f]+|[-+]?\d+)"
    r">(?P<after>[-+]?0x[0-9A-Fa-f]+|[-+]?\d+)$"
)
_LOAD_RE = re.compile(
    r"^[^,]+,\s*(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*"
    r"\(\s*(?P<base>[rf]\d+)\s*\)"
)
_GLOBAL_FIELD_BASE_RE = re.compile(
    r"^(?:lbl_[0-9A-Fa-f]{8}|[A-Za-z_][A-Za-z0-9_]*_80[0-9A-Fa-f]{6})$"
)
_PRIORITY_UNAVAILABLE = "PRIORITY_UNAVAILABLE"
_PRIORITY_UNAVAILABLE_RATIONALE = (
    "priority data unavailable; window_gap describes output adjacency only, "
    "not a scheduler decision margin"
)


def parse_schedule_rules(text: str) -> tuple[ScheduleRule, ...]:
    rules: list[ScheduleRule] = []
    for raw in text.split(","):
        item = raw.strip()
        if not item:
            continue
        match = _RULE_RE.match(item)
        if not match:
            raise ValueError(
                f"invalid schedule rule {item!r}; expected opcode:before>after"
            )
        rules.append(ScheduleRule(
            opcode=match.group("opcode"),
            before_offset=int(match.group("before"), 0),
            after_offset=int(match.group("after"), 0),
            raw=item,
        ))
    if not rules:
        raise ValueError("at least one schedule rule is required")
    return tuple(rules)


def _load_operands(inst: Instruction) -> tuple[int, str] | None:
    match = _LOAD_RE.match(inst.operands)
    if not match:
        return None
    return int(match.group("offset"), 0), match.group("base")


def _reg_num(reg: str | None) -> int | None:
    if not reg or len(reg) < 2:
        return None
    try:
        return int(reg[1:], 10)
    except ValueError:
        return None


def _line_col(source: str, char_index: int) -> tuple[int, int]:
    line = source.count("\n", 0, char_index) + 1
    prev_nl = source.rfind("\n", 0, char_index)
    col = char_index if prev_nl < 0 else char_index - prev_nl - 1
    return line, col


@dataclass(frozen=True)
class _IrLoad:
    opcode: str
    offset: int
    block: int
    index: int
    operands: str
    dest_virtual: int | None
    base_virtual: int | None

    @property
    def node_id(self) -> str:
        return f"B{self.block}:{self.index}"


def _source_pass_for(fn: Function, selected: Pass) -> Pass | None:
    pre_schedule = fn.get_pass("AFTER INSTRUCTION SCHEDULING")
    if pre_schedule is not None and pre_schedule is not selected:
        return pre_schedule
    pre = fn.last_precolor_pass()
    if pre is not selected:
        return pre
    return None


def _collect_ir_loads(pre_pass: Pass | None) -> dict[tuple[str, int], list[_IrLoad]]:
    if pre_pass is None:
        return {}
    loads: dict[tuple[str, int], list[_IrLoad]] = {}
    for block in pre_pass.blocks:
        for index, inst in enumerate(block.instructions):
            load = _load_operands(inst)
            if load is None:
                continue
            offset, base = load
            dest_virtual = None
            if inst.regs:
                kind, num = inst.regs[0]
                if kind == "r":
                    dest_virtual = num
            entry = _IrLoad(
                opcode=inst.opcode,
                offset=offset,
                block=block.index,
                index=index,
                operands=inst.operands,
                dest_virtual=dest_virtual,
                base_virtual=_reg_num(base),
            )
            loads.setdefault((inst.opcode, offset), []).append(entry)
    return loads


def _bindings_by_virtual(source_text: str, function: str, pre_pass: Pass | None) -> dict[int, object]:
    if not source_text or pre_pass is None:
        return {}
    try:
        from .symbol_bridge import list_bindings
        bindings = list_bindings(source_text, function, pre_pass)
    except Exception:
        return {}
    return {
        getattr(binding, "virtual"): binding
        for binding in bindings
        if getattr(binding, "virtual", -1) >= 0
    }


def _find_source_expression(
    source_text: str,
    *,
    base_var: str,
    offset: int,
) -> tuple[str, str | None, int | None, int | None, str]:
    field_name = f"x{offset:X}"
    patterns = [
        re.compile(
            rf"\b{re.escape(base_var)}\s*->\s*{re.escape(field_name)}\b"
        ),
        re.compile(
            rf"\b{re.escape(base_var)}\s*\.\s*{re.escape(field_name)}\b"
        ),
        re.compile(
            rf"\b{re.escape(base_var)}\b[^;\n]*\+\s*0x{offset:X}\b"
        ),
    ]
    for pattern in patterns:
        match = pattern.search(source_text)
        if match:
            line, col = _line_col(source_text, match.start())
            expr = re.sub(r"\s+", "", match.group(0))
            return expr, field_name, line, col, "source-expression"
    return (
        f"{base_var}->field_at_0x{offset:X}",
        None,
        None,
        None,
        "field-offset",
    )


def _looks_like_global_field_base(name: str) -> bool:
    return _GLOBAL_FIELD_BASE_RE.match(name) is not None


def _find_global_source_expression(
    source_text: str,
    *,
    offset: int,
) -> tuple[str, str, str, int, int] | None:
    field_name = f"x{offset:X}"
    patterns = [
        re.compile(
            rf"\b(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s*->\s*"
            rf"{re.escape(field_name)}\b"
        ),
        re.compile(
            rf"\b(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"
            rf"{re.escape(field_name)}\b"
        ),
    ]
    matches: list[tuple[int, re.Match[str]]] = []
    for pattern in patterns:
        for match in pattern.finditer(source_text):
            base_var = match.group("base")
            if _looks_like_global_field_base(base_var):
                matches.append((match.start(), match))
    if not matches:
        return None
    _, match = min(matches, key=lambda item: item[0])
    line, col = _line_col(source_text, match.start())
    expr = re.sub(r"\s+", "", match.group(0))
    return expr, field_name, match.group("base"), line, col


def _source_for_ir_load(
    ir_load: _IrLoad,
    *,
    bindings: dict[int, object],
    source_text: str,
    source_file: str | None,
) -> ScheduleSource:
    base_binding = bindings.get(ir_load.base_virtual)
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
    confidence = "ir-node"
    if base_var:
        expression, field_name, line, col, confidence = _find_source_expression(
            source_text,
            base_var=base_var,
            offset=ir_load.offset,
        )
        if line is None:
            line = getattr(base_binding, "decl_line", None)
    else:
        global_expr = _find_global_source_expression(
            source_text,
            offset=ir_load.offset,
        )
        if global_expr is not None:
            expression, field_name, base_var, line, col = global_expr
            base_confidence = "global-source-expression"
            confidence = "source-expression"
    return ScheduleSource(
        ir_node_id=ir_load.node_id,
        ir_virtual=ir_load.dest_virtual,
        base_virtual=ir_load.base_virtual,
        base_var=base_var,
        base_confidence=base_confidence,
        source_file=source_file,
        source_line=line,
        source_col=col,
        expression=expression,
        field_offset=ir_load.offset,
        field_name=field_name,
        confidence=confidence,
    )


def _attach_source_provenance(
    report: ScheduleExplainReport,
    *,
    fn: Function,
    selected: Pass,
    source_text: str | None,
    source_file: str | None,
) -> ScheduleExplainReport:
    if not source_text:
        return report
    pre_pass = _source_pass_for(fn, selected)
    ir_loads = {
        key: list(value)
        for key, value in _collect_ir_loads(pre_pass).items()
    }
    if not ir_loads:
        return report
    bindings = _bindings_by_virtual(source_text, report.function, pre_pass)

    decisions: list[ScheduleDecision] = []
    for decision in report.decisions:
        candidates: list[ScheduleCandidate] = []
        for cand in decision.candidates:
            source = cand.source
            if cand.offset is not None:
                bucket = ir_loads.get((cand.opcode, cand.offset))
                if bucket:
                    source = _source_for_ir_load(
                        bucket.pop(0),
                        bindings=bindings,
                        source_text=source_text,
                        source_file=source_file,
                    )
            candidates.append(replace(cand, source=source))
        decisions.append(replace(decision, candidates=tuple(candidates)))
    return replace(report, decisions=tuple(decisions))


def _picked_candidate(decision: ScheduleDecision) -> ScheduleCandidate | None:
    preferred_roles = (
        ("observed-first", "target-first", "target-second")
        if decision.status == "matched"
        else ("target-first", "observed-first", "target-second")
    )
    for role in preferred_roles:
        for cand in decision.candidates:
            if cand.role == role and cand.offset is not None:
                return cand
    for cand in decision.candidates:
        if cand.offset is not None:
            return cand
    return None


def _decision_margin(
    real: ScheduleDecision,
    forced: ScheduleDecision,
) -> int | None:
    _ = (real, forced)
    return None


def diff_schedule(
    real_pcdump_text: str,
    forced_pcdump_text: str,
    *,
    function: str,
    force_schedule: str,
    source_text: str | None = None,
    source_file: str | None = None,
) -> ScheduleDiffReport:
    real = explain_schedule(
        real_pcdump_text,
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_file,
    )
    forced = explain_schedule(
        forced_pcdump_text,
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_file,
    )

    finding = None
    for step, (real_decision, forced_decision) in enumerate(
        zip(real.decisions, forced.decisions),
        1,
    ):
        real_pick = _picked_candidate(real_decision)
        forced_pick = _picked_candidate(forced_decision)
        real_key = (
            real_decision.status,
            real_pick.opcode if real_pick else None,
            real_pick.offset if real_pick else None,
        )
        forced_key = (
            forced_decision.status,
            forced_pick.opcode if forced_pick else None,
            forced_pick.offset if forced_pick else None,
        )
        if real_key == forced_key:
            continue
        finding = ScheduleDiffFinding(
            step=step,
            rule=real_decision.rule,
            real_status=real_decision.status,
            forced_status=forced_decision.status,
            real_heuristic_verdict=real_decision.heuristic_verdict,
            forced_heuristic_verdict=forced_decision.heuristic_verdict,
            real_window_gap=real_decision.window_gap,
            forced_window_gap=forced_decision.window_gap,
            margin=_decision_margin(real_decision, forced_decision),
            real_pick=real_pick,
            forced_pick=forced_pick,
            rationale=(
                "first scheduler-window decision whose picked load differs "
                "between real and forced paths"
            ),
        )
        break

    return ScheduleDiffReport(
        function=function,
        real_pass_name=real.pass_name,
        forced_pass_name=forced.pass_name,
        finding=finding,
        real=real,
        forced=forced,
    )


def _candidate(
    *,
    role: str,
    inst: Instruction,
    offset: int,
    base: str,
    window_rank: int,
    block: int,
    index: int,
) -> ScheduleCandidate:
    return ScheduleCandidate(
        role=role,
        opcode=inst.opcode,
        operands=inst.operands,
        offset=offset,
        base=base,
        window_rank=window_rank,
        block=block,
        index=index,
        instruction_class="same-base-load",
    )


def _explain_rule_in_pass(function_pass, rule: ScheduleRule) -> ScheduleDecision:
    for block in function_pass.blocks:
        insts = block.instructions
        for i, inst in enumerate(insts):
            if inst.opcode != rule.opcode:
                continue
            load = _load_operands(inst)
            if load is None:
                continue
            offset, base = load

            if offset == rule.before_offset:
                next_inst = insts[i + 1] if i + 1 < len(insts) else None
                if next_inst and next_inst.opcode == rule.opcode:
                    next_load = _load_operands(next_inst)
                    if (
                        next_load is not None
                        and next_load[0] == rule.after_offset
                        and next_load[1] == base
                    ):
                        return ScheduleDecision(
                            rule=rule,
                            status="already-target",
                            heuristic_verdict=_PRIORITY_UNAVAILABLE,
                            window_gap=0,
                            block=block.index,
                            candidates=(
                                _candidate(
                                    role="target-first",
                                    inst=inst,
                                    offset=offset,
                                    base=base,
                                    window_rank=0,
                                    block=block.index,
                                    index=i,
                                ),
                                _candidate(
                                    role="target-second",
                                    inst=next_inst,
                                    offset=next_load[0],
                                    base=next_load[1],
                                    window_rank=0,
                                    block=block.index,
                                    index=i + 1,
                                ),
                            ),
                            rationale=(
                                "target order is already present for adjacent "
                                "same-base loads; "
                                f"{_PRIORITY_UNAVAILABLE_RATIONALE}"
                            ),
                        )
                third = insts[i + 2] if i + 2 < len(insts) else None
                if third and third.opcode == rule.opcode:
                    third_load = _load_operands(third)
                    if (
                        third_load is not None
                        and third_load[0] == rule.after_offset
                        and third_load[1] == base
                    ):
                        middle = insts[i + 1]
                        return ScheduleDecision(
                            rule=rule,
                            status="already-target",
                            heuristic_verdict=_PRIORITY_UNAVAILABLE,
                            window_gap=1,
                            block=block.index,
                            candidates=(
                                _candidate(
                                    role="target-first",
                                    inst=inst,
                                    offset=offset,
                                    base=base,
                                    window_rank=0,
                                    block=block.index,
                                    index=i,
                                ),
                                ScheduleCandidate(
                                    role="intervening",
                                    opcode=middle.opcode,
                                    operands=middle.operands,
                                    offset=None,
                                    base=None,
                                    window_rank=1,
                                    block=block.index,
                                    index=i + 1,
                                ),
                                _candidate(
                                    role="target-second",
                                    inst=third,
                                    offset=third_load[0],
                                    base=third_load[1],
                                    window_rank=1,
                                    block=block.index,
                                    index=i + 2,
                                ),
                            ),
                            rationale=(
                                "target order is already present across one "
                                "intervening instruction for same-base loads; "
                                f"{_PRIORITY_UNAVAILABLE_RATIONALE}"
                            ),
                        )
                continue

            if offset != rule.after_offset:
                continue
            next_inst = insts[i + 1] if i + 1 < len(insts) else None
            if next_inst and next_inst.opcode == rule.opcode:
                next_load = _load_operands(next_inst)
                if (
                    next_load is not None
                    and next_load[0] == rule.before_offset
                    and next_load[1] == base
                ):
                    return ScheduleDecision(
                        rule=rule,
                        status="matched",
                        heuristic_verdict=_PRIORITY_UNAVAILABLE,
                        window_gap=0,
                        block=block.index,
                        candidates=(
                            _candidate(
                                role="observed-first",
                                inst=inst,
                                offset=offset,
                                base=base,
                                window_rank=0,
                                block=block.index,
                                index=i,
                            ),
                            _candidate(
                                role="target-first",
                                inst=next_inst,
                                offset=next_load[0],
                                base=next_load[1],
                                window_rank=0,
                                block=block.index,
                                index=i + 1,
                            ),
                        ),
                        rationale=(
                            "adjacent same-base loads observed in non-target "
                            "order; "
                            f"{_PRIORITY_UNAVAILABLE_RATIONALE}"
                        ),
                    )

            third = insts[i + 2] if i + 2 < len(insts) else None
            if third and third.opcode == rule.opcode:
                third_load = _load_operands(third)
                if (
                    third_load is not None
                    and third_load[0] == rule.before_offset
                    and third_load[1] == base
                ):
                    middle = insts[i + 1]
                    return ScheduleDecision(
                        rule=rule,
                        status="matched",
                        heuristic_verdict=_PRIORITY_UNAVAILABLE,
                        window_gap=1,
                        block=block.index,
                        candidates=(
                            _candidate(
                                role="observed-first",
                                inst=inst,
                                offset=offset,
                                base=base,
                                window_rank=0,
                                block=block.index,
                                index=i,
                            ),
                            ScheduleCandidate(
                                role="intervening",
                                opcode=middle.opcode,
                                operands=middle.operands,
                                offset=None,
                                base=None,
                                window_rank=1,
                                block=block.index,
                                index=i + 1,
                            ),
                            _candidate(
                                role="target-first",
                                inst=third,
                                offset=third_load[0],
                                base=third_load[1],
                                window_rank=1,
                                block=block.index,
                                index=i + 2,
                            ),
                        ),
                        rationale=(
                            "one intervening instruction separates the target "
                            "same-base load pair; "
                            f"{_PRIORITY_UNAVAILABLE_RATIONALE}"
                        ),
                    )

    return ScheduleDecision(
        rule=rule,
        status="missing",
        heuristic_verdict="UNKNOWN",
        window_gap=None,
        rationale=(
            "no adjacent or one-instruction-straddled same-base load window "
            "matched this rule"
        ),
    )


def _annotate_load_window(decision: ScheduleDecision) -> ScheduleDecision:
    if decision.status not in {"matched", "already-target"}:
        return decision
    if not any(
        cand.instruction_class == "same-base-load"
        for cand in decision.candidates
    ):
        return decision
    return replace(
        decision,
        window_kind="same-base-load",
        forceability="forceable-by-load-hook",
    )


def _asm_candidate(
    cand: AsmWindowCandidate,
    *,
    window_rank: int,
) -> ScheduleCandidate:
    return ScheduleCandidate(
        role=cand.role,
        opcode=cand.opcode,
        operands=cand.operands,
        offset=None,
        base=None,
        window_rank=window_rank,
        block=0,
        index=cand.current_index,
        code_offset=cand.code_offset,
        instruction_class=cand.instruction_class,
    )


def _source_hint(
    source_text: str | None,
    pattern: re.Pattern[str],
) -> tuple[str | None, int | None, int | None]:
    if not source_text:
        return None, None, None
    match = pattern.search(source_text)
    if not match:
        return None, None, None
    line, col = _line_col(source_text, match.start())
    return re.sub(r"\s+", "", match.group(0)), line, col


def _source_reshapes_for_addi_pair(
    result: AsmWindowResult,
    *,
    source_text: str | None,
    source_file: str | None,
) -> tuple[ScheduleSourceReshape, ...]:
    if result.source_shape_verdict != "source-shape-controllable":
        return ()
    classes = {cand.instruction_class for cand in result.candidates}
    if {"local-address-materialization", "counter-increment"} - classes:
        return ()

    local = next(
        cand for cand in result.candidates
        if cand.instruction_class == "local-address-materialization"
    )
    counter = next(
        cand for cand in result.candidates
        if cand.instruction_class == "counter-increment"
    )
    local_expr, local_line, local_col = _source_hint(
        source_text,
        re.compile(r"&\s*[A-Za-z_][A-Za-z0-9_]*"),
    )
    counter_expr, counter_line, counter_col = _source_hint(
        source_text,
        re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*(?:\+\+|\+=\s*1)"),
    )
    vector_expr, vector_line, vector_col = _source_hint(
        source_text,
        re.compile(r"\bVec3\s+[A-Za-z_][A-Za-z0-9_]*\b"),
    )
    local_observed = f"{local.opcode} {local.operands}"
    counter_observed = f"{counter.opcode} {counter.operands}"

    return (
        ScheduleSourceReshape(
            rank=1,
            kind="delay-local-address-materialization",
            title="Delay local stack address materialization",
            mechanically_applicable=False,
            target_expression=local_expr,
            observed_expression=local_observed,
            source_file=source_file if local_line is not None else None,
            source_line=local_line,
            source_col=local_col,
            patch_hint=(
                "Materialize the stack-local address as close as possible to "
                "the call that consumes it; for example keep &dir inside the "
                "lbVector_Normalize(&dir) statement instead of creating an "
                "earlier pointer-like temporary."
            ),
            rationale=(
                "the observed-first addi materializes a stack-local address "
                "before the target counter increment"
            ),
        ),
        ScheduleSourceReshape(
            rank=2,
            kind="anchor-counter-increment",
            title="Anchor the counter increment before local-vector work",
            mechanically_applicable=False,
            target_expression=counter_expr,
            observed_expression=counter_observed,
            source_file=source_file if counter_line is not None else None,
            source_line=counter_line,
            source_col=counter_col,
            patch_hint=(
                "Keep count++ as its own statement immediately before the "
                "local-vector work, or try count += 1 / preincrement as a "
                "source-shape probe if MWCC still sinks it."
            ),
            rationale=(
                "the target-first addi is a self increment that should anchor "
                "before local address materialization"
            ),
        ),
        ScheduleSourceReshape(
            rank=3,
            kind="split-local-vector-lifetime",
            title="Split the local vector lifetime",
            mechanically_applicable=False,
            target_expression=vector_expr,
            observed_expression=local_observed,
            source_file=source_file if vector_line is not None else None,
            source_line=vector_line,
            source_col=vector_col,
            patch_hint=(
                "Narrow the Vec3 dir lifetime by declaring it in the smallest "
                "block that contains the stores and first address-taking call."
            ),
            rationale=(
                "a narrower stack-local lifetime can delay the address-taking "
                "addi without changing the load window"
            ),
        ),
        ScheduleSourceReshape(
            rank=4,
            kind="reorder-counter-and-local-block",
            title="Check counter/local source order",
            mechanically_applicable=False,
            target_expression=counter_expr,
            observed_expression=local_expr,
            source_file=source_file if counter_line is not None else None,
            source_line=counter_line,
            source_col=counter_col,
            patch_hint=(
                "If the source already has count++ before Vec3 dir work, the "
                "natural source order is already target-like and stronger "
                "source reshapes are needed before calling this a backend "
                "ceiling."
            ),
            rationale=(
                "source order is a useful first probe, but this pattern may "
                "also require lifetime or expression-shape changes"
            ),
        ),
    )


def _decision_from_asm_window(
    decision: ScheduleDecision,
    result: AsmWindowResult,
    *,
    source_text: str | None,
    source_file: str | None,
) -> ScheduleDecision:
    candidates = tuple(
        _asm_candidate(cand, window_rank=rank)
        for rank, cand in enumerate(result.candidates)
    )
    return replace(
        decision,
        status=result.status,
        heuristic_verdict=result.heuristic_verdict,
        window_gap=result.window_gap,
        rationale=result.rationale,
        candidates=candidates,
        window_kind="asm-code-offset",
        forceability=result.forceability,
        source_shape_verdict=result.source_shape_verdict,
        source_reshapes=_source_reshapes_for_addi_pair(
            result,
            source_text=source_text,
            source_file=source_file,
        ),
    )


def _attach_asm_windows(
    report: ScheduleExplainReport,
    *,
    target_asm: list[str] | None,
    current_asm: list[str] | None,
    source_text: str | None,
    source_file: str | None,
) -> ScheduleExplainReport:
    if target_asm is None or current_asm is None:
        return report
    decisions: list[ScheduleDecision] = []
    for decision in report.decisions:
        if decision.status != "missing":
            decisions.append(decision)
            continue
        if is_memory_load_opcode(decision.rule.opcode):
            decisions.append(decision)
            continue
        result = explain_code_offset_window(
            decision.rule,
            target_asm,
            current_asm,
            source_text=source_text,
            source_file=source_file,
        )
        if result is None or result.status == "missing":
            decisions.append(decision)
            continue
        decisions.append(_decision_from_asm_window(
            decision,
            result,
            source_text=source_text,
            source_file=source_file,
        ))
    return replace(report, decisions=tuple(decisions))


def explain_schedule(
    pcdump_text: str,
    *,
    function: str,
    force_schedule: str,
    source_text: str | None = None,
    source_file: str | None = None,
    target_asm: list[str] | None = None,
    current_asm: list[str] | None = None,
    checkdiff_classification: dict | None = None,
) -> ScheduleExplainReport:
    _ = checkdiff_classification
    rules = parse_schedule_rules(force_schedule)
    functions = parse_pcdump(pcdump_text, function=function)
    if not functions:
        report = ScheduleExplainReport(function=function, pass_name=None, decisions=tuple(
            ScheduleDecision(
                rule=rule,
                status="missing",
                heuristic_verdict="UNKNOWN",
                window_gap=None,
                rationale=f"function {function} was not found in pcdump",
            )
            for rule in rules
        ))
        return _attach_asm_windows(
            report,
            target_asm=target_asm,
            current_asm=current_asm,
            source_text=source_text,
            source_file=source_file,
        )

    fn = functions[0]
    selected = (
        fn.get_pass("FINAL CODE AFTER INSTRUCTION SCHEDULING")
        or fn.get_pass("AFTER INSTRUCTION SCHEDULING")
    )
    if selected is None:
        report = ScheduleExplainReport(function=function, pass_name=None, decisions=tuple(
            ScheduleDecision(
                rule=rule,
                status="missing",
                heuristic_verdict="UNKNOWN",
                window_gap=None,
                rationale="pcdump has no instruction-scheduling pass",
            )
            for rule in rules
        ))
        return _attach_asm_windows(
            report,
            target_asm=target_asm,
            current_asm=current_asm,
            source_text=source_text,
            source_file=source_file,
        )
    report = ScheduleExplainReport(
        function=function,
        pass_name=selected.name,
        decisions=tuple(
            _annotate_load_window(_explain_rule_in_pass(selected, rule))
            for rule in rules
        ),
    )
    report = _attach_asm_windows(
        report,
        target_asm=target_asm,
        current_asm=current_asm,
        source_text=source_text,
        source_file=source_file,
    )
    return _attach_source_provenance(
        report,
        fn=fn,
        selected=selected,
        source_text=source_text,
        source_file=source_file,
    )


def render_text(report: ScheduleExplainReport) -> str:
    lines = [f"explain-schedule - {report.function}"]
    if report.pass_name:
        lines.append(f"pass: {report.pass_name}")
    for decision in report.decisions:
        rule = decision.rule
        window_gap = (
            "unknown" if decision.window_gap is None
            else str(decision.window_gap)
        )
        lines.append("")
        rule_bits = [
            f"status={decision.status}",
            f"heuristic_verdict={decision.heuristic_verdict}",
            f"window_gap={window_gap}",
        ]
        if decision.window_kind:
            rule_bits.append(f"window_kind={decision.window_kind}")
        if decision.forceability:
            rule_bits.append(f"forceability={decision.forceability}")
        if decision.source_shape_verdict:
            rule_bits.append(
                f"source_shape_verdict={decision.source_shape_verdict}"
            )
        lines.append(f"rule {rule.raw}: " + " ".join(rule_bits))
        if decision.block is not None:
            lines.append(f"  block: B{decision.block}")
        lines.append(f"  rationale: {decision.rationale}")
        for cand in decision.candidates:
            offset = "?" if cand.offset is None else f"0x{cand.offset:X}"
            base = cand.base or "?"
            cand_bits = [
                f"offset={offset}",
                f"base={base}",
                f"window_rank={cand.window_rank}",
                f"index={cand.index}",
            ]
            if cand.code_offset is not None:
                cand_bits.append(f"code_offset=0x{cand.code_offset:X}")
            if cand.instruction_class:
                cand_bits.append(f"class={cand.instruction_class}")
            source_suffix = ""
            if cand.source is not None:
                src = cand.source
                bits = []
                if src.ir_node_id:
                    bits.append(f"ir={src.ir_node_id}")
                if src.source_file and src.source_line is not None:
                    loc = f"{src.source_file}:{src.source_line}"
                    if src.source_col is not None:
                        loc += f":{src.source_col}"
                    bits.append(f"source={loc}")
                if src.expression:
                    bits.append(f"expr={src.expression}")
                if src.field_offset is not None:
                    bits.append(f"field_offset=0x{src.field_offset:X}")
                if src.base_var:
                    bits.append(f"base_var={src.base_var}")
                bits.append(f"source_confidence={src.confidence}")
                source_suffix = " " + " ".join(bits)
            lines.append(
                f"  - {cand.role}: {cand.opcode} {cand.operands} "
                f"{' '.join(cand_bits)}{source_suffix}"
            )
        if decision.source_reshapes:
            lines.append("  source reshapes:")
            for reshape in decision.source_reshapes:
                loc = ""
                if reshape.source_file and reshape.source_line is not None:
                    loc = f" source={reshape.source_file}:{reshape.source_line}"
                    if reshape.source_col is not None:
                        loc += f":{reshape.source_col}"
                lines.append(
                    f"    {reshape.rank}. {reshape.kind}: "
                    f"{reshape.title}{loc}"
                )
                lines.append(f"       hint: {reshape.patch_hint}")
    return "\n".join(lines)


def _format_candidate_source(cand: ScheduleCandidate | None) -> str:
    if cand is None:
        return "none"
    offset = "?" if cand.offset is None else f"0x{cand.offset:X}"
    parts = [
        f"{cand.role} {cand.opcode} {cand.operands}",
        f"offset={offset}",
        f"index={cand.index}",
    ]
    if cand.source is not None:
        src = cand.source
        if src.ir_node_id:
            parts.append(f"ir={src.ir_node_id}")
        if src.source_file and src.source_line is not None:
            loc = f"{src.source_file}:{src.source_line}"
            if src.source_col is not None:
                loc += f":{src.source_col}"
            parts.append(f"source={loc}")
        if src.expression:
            parts.append(f"expr={src.expression}")
        if src.field_offset is not None:
            parts.append(f"field_offset=0x{src.field_offset:X}")
        if src.base_var:
            parts.append(f"base_var={src.base_var}")
        parts.append(f"source_confidence={src.confidence}")
    return " ".join(parts)


def render_diff_text(report: ScheduleDiffReport) -> str:
    lines = [f"diff-schedule - {report.function}"]
    if report.real_pass_name:
        lines.append(f"real pass: {report.real_pass_name}")
    if report.forced_pass_name:
        lines.append(f"forced pass: {report.forced_pass_name}")
    finding = report.finding
    if finding is None:
        lines.append("no divergent scheduler-window decision found")
        return "\n".join(lines)
    margin = (
        "priority data unavailable" if finding.margin is None
        else str(finding.margin)
    )
    lines.extend([
        "",
        f"first divergence: step={finding.step} rule={finding.rule.raw}",
        f"  real: status={finding.real_status} "
        f"heuristic_verdict={finding.real_heuristic_verdict} "
        f"window_gap={finding.real_window_gap}",
        f"  forced: status={finding.forced_status} "
        f"heuristic_verdict={finding.forced_heuristic_verdict} "
        f"window_gap={finding.forced_window_gap}",
        f"  margin={margin}",
        f"  real picked {_format_candidate_source(finding.real_pick)}",
        f"  forced picked {_format_candidate_source(finding.forced_pick)}",
        f"  rationale: {finding.rationale}",
    ])
    return "\n".join(lines)


def render_json(report: ScheduleExplainReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_diff_json(report: ScheduleDiffReport) -> str:
    return json.dumps(asdict(report), indent=2)
