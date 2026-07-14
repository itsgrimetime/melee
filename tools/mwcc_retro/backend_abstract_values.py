"""Bounded interprocedural abstract value/type analysis for retail MWCC PE.

Consumes the strict PE, raw CFG, and control-target result from Task 4.
The analysis is a deterministic SCC/fixed-point abstract interpreter over
x86 registers, stack arguments/locals, return values, statically addressed
memory, and call summaries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Sequence

from capstone import CS_GRP_CALL, CS_GRP_IRET, CS_GRP_JUMP, CS_GRP_RET
from capstone.x86 import (
    X86_INS_JMP,
    X86_INS_LEA,
    X86_INS_MOV,
    X86_INS_MOVSX,
    X86_INS_MOVZX,
    X86_OP_IMM,
    X86_OP_MEM,
    X86_OP_REG,
    X86_REG_INVALID,
)

from tools.mwcc_retro.pe import Image
from tools.mwcc_retro.x86_cfg import (
    AnalysisLimits,
    ControlTargetResult,
    Instruction,
    RawCfg,
)

# ── Abstract value ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AbstractValue:
    """One value in the abstract lattice.

    ``kind`` is one of ``bottom``, ``exact``, ``finite``, ``affine``,
    ``null``, ``pointer``, or ``unknown``.

    ``values`` holds the finite set for exact/finite kinds.
    ``origin`` records the producing instruction address and reason.
    """

    kind: str = "bottom"
    values: frozenset[int] = frozenset()
    affine_base: int = 0
    affine_stride: int = 0
    affine_symbol: str = ""
    pointer_base: int = 0
    pointer_type: str = ""
    origin: str = ""

    @property
    def is_bottom(self) -> bool:
        return self.kind == "bottom"

    @property
    def is_exact(self) -> bool:
        return self.kind == "exact" and len(self.values) == 1

    @property
    def exact_value(self) -> int | None:
        return next(iter(self.values)) if self.is_exact else None

    @property
    def is_unknown(self) -> bool:
        return self.kind == "unknown"

    @property
    def is_finite(self) -> bool:
        return self.kind in {"exact", "finite"}

    def join(self, other: AbstractValue) -> AbstractValue:
        if self.is_bottom:
            return other
        if other.is_bottom:
            return self
        if self == other:
            return self

        both_finite = self.is_finite and other.is_finite
        if both_finite:
            merged = self.values | other.values
            if len(merged) == 1:
                return AbstractValue(
                    kind="exact",
                    values=merged,
                    origin=f"join({self.origin},{other.origin})",
                )
            return AbstractValue(
                kind="finite",
                values=merged,
                origin=f"join({self.origin},{other.origin})",
            )

        return AbstractValue(kind="unknown", origin=f"join({self.kind},{other.kind})")


_BOTTOM = AbstractValue(kind="bottom")


def _exact(value: int, origin: str = "") -> AbstractValue:
    return AbstractValue(kind="exact", values=frozenset({value}), origin=origin)


def _unknown(origin: str = "") -> AbstractValue:
    return AbstractValue(kind="unknown", origin=origin)


# ── Machine state ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MachineState:
    """Abstract register + stack-local state at a program point."""

    registers: tuple[AbstractValue, ...]  # indexed by Capstone reg id
    stack_locals: tuple[tuple[int, AbstractValue], ...] = ()  # (offset, val)

    @staticmethod
    def empty() -> MachineState:
        return MachineState(registers=tuple(_BOTTOM for _ in range(256)))

    def register(self, reg_id: int) -> AbstractValue:
        if 0 <= reg_id < len(self.registers):
            return self.registers[reg_id]
        return _BOTTOM

    def with_register(self, reg_id: int, value: AbstractValue) -> MachineState:
        regs = list(self.registers)
        while len(regs) <= reg_id:
            regs.append(_BOTTOM)
        regs[reg_id] = value
        return MachineState(registers=tuple(regs), stack_locals=self.stack_locals)

    def stack_local(self, offset: int) -> AbstractValue:
        for off, val in self.stack_locals:
            if off == offset:
                return val
        return _BOTTOM

    def with_stack_local(
        self, offset: int, value: AbstractValue
    ) -> MachineState:
        new_locals = tuple(
            (off, val) for off, val in self.stack_locals if off != offset
        ) + ((offset, value),)
        return MachineState(registers=self.registers, stack_locals=new_locals)


# ── Function summary ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FunctionSummary:
    """Per-function call summary from interprocedural analysis."""

    entry: int
    argument_flows: tuple[tuple[int, AbstractValue], ...] = ()
    allocations: tuple[tuple[int, str, AbstractValue], ...] = ()
    typed_writes: tuple[tuple[int, int, AbstractValue, str], ...] = ()
    return_value: AbstractValue = field(
        default_factory=lambda: _BOTTOM
    )
    callees: tuple[int, ...] = ()

    @staticmethod
    def empty(entry: int) -> FunctionSummary:
        return FunctionSummary(entry=entry)


# ── Analysis result ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Completed interprocedural value/type analysis."""

    compiler_sha256: str
    cfg_instruction_hash: str
    summaries: tuple[FunctionSummary, ...]
    unresolved: tuple[tuple[int, str], ...] = ()
    proof_ready: bool = False
    limits: AnalysisLimits | None = None
    high_water_marks: tuple[tuple[str, int], ...] = ()

    def summary_at(self, address: int) -> FunctionSummary | None:
        for s in self.summaries:
            if s.entry == address:
                return s
        return None


# ── x86 transfer helpers ───────────────────────────────────────────────────


def _register_family(decoder, register: int) -> str:
    name = decoder.reg_name(register)
    families = {
        "al": "eax", "ah": "eax", "ax": "eax", "eax": "eax",
        "bl": "ebx", "bh": "ebx", "bx": "ebx", "ebx": "ebx",
        "cl": "ecx", "ch": "ecx", "cx": "ecx", "ecx": "ecx",
        "dl": "edx", "dh": "edx", "dx": "edx", "edx": "edx",
        "sil": "esi", "si": "esi", "esi": "esi",
        "dil": "edi", "di": "edi", "edi": "edi",
        "bpl": "ebp", "bp": "ebp", "ebp": "ebp",
        "spl": "esp", "sp": "esp", "esp": "esp",
    }
    return families.get(name, name)


def _instruction_at(cfg: RawCfg, address: int) -> Instruction | None:
    for row in cfg.instructions:
        if row.address == address:
            return row
    return None


def _block_containing(cfg: RawCfg, address: int) -> int | None:
    for block in cfg.blocks:
        addrs = block.instruction_addresses
        if addrs and addrs[0] <= address <= addrs[-1]:
            return block.start
    return None


def _block_end(cfg: RawCfg, block_start: int) -> int:
    for block in cfg.blocks:
        if block.start == block_start:
            addrs = block.instruction_addresses
            if addrs:
                last_insn = _instruction_at(cfg, addrs[-1])
                if last_insn:
                    return addrs[-1] + last_insn.size
    return block_start


def _owning_function(cfg: RawCfg, address: int) -> int | None:
    entries = sorted(
        (e.address for e in cfg.function_entries), reverse=True
    )
    for entry in entries:
        if entry <= address:
            return entry
    return None


# ── Transfer function ──────────────────────────────────────────────────────


class _TransferFunctions:
    """Evaluates one x86 instruction's effect on the abstract state."""

    def __init__(self, image: Image, cfg: RawCfg):
        self.image = image
        self.cfg = cfg
        self._insn_map: dict[int, Instruction] = {
            row.address: row for row in cfg.instructions
        }
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32

        self.decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        self.decoder.detail = True
        self._decoded: dict[int, Any] = {}

    def _decode(self, address: int):
        if address in self._decoded:
            return self._decoded[address]
        insn = self._insn_map.get(address)
        if insn is None:
            raise ValueError(f"no instruction at {address:#x}")
        raw = self.image.read(address, insn.size)
        decoded = next(self.decoder.disasm(raw, address))
        self._decoded[address] = decoded
        return decoded

    def eval(self, state: MachineState, address: int) -> MachineState:
        decoded = self._decode(address)

        # Terminal instructions: state flows through CFG edges only
        if (
            decoded.group(CS_GRP_CALL)
            or decoded.group(CS_GRP_RET)
            or decoded.group(CS_GRP_IRET)
        ):
            return state
        if decoded.id == X86_INS_JMP and decoded.group(CS_GRP_JUMP):
            return state

        # MOV reg, reg
        if (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_REG
            and decoded.operands[1].type == X86_OP_REG
        ):
            src = state.register(decoded.operands[1].reg)
            return state.with_register(decoded.operands[0].reg, src)

        # MOV reg, imm
        if (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_REG
            and decoded.operands[1].type == X86_OP_IMM
        ):
            value = decoded.operands[1].imm & 0xFFFF_FFFF
            return state.with_register(
                decoded.operands[0].reg,
                _exact(value, origin=f"{address:#x}"),
            )

        # MOV reg, [absolute]
        if (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_REG
            and decoded.operands[1].type == X86_OP_MEM
        ):
            mem = decoded.operands[1].mem
            if (
                mem.segment == X86_REG_INVALID
                and mem.base == X86_REG_INVALID
                and mem.index == X86_REG_INVALID
            ):
                absolute = mem.disp & 0xFFFF_FFFF
                try:
                    raw = self.image.read(absolute, decoded.operands[0].size)
                    if decoded.operands[0].size == 4:
                        val = int.from_bytes(raw, "little")
                        return state.with_register(
                            decoded.operands[0].reg,
                            _exact(val, origin=f"global:{absolute:#x}"),
                        )
                except ValueError:
                    pass
            # Register-based memory: try to resolve
            if mem.base != X86_REG_INVALID and mem.index == X86_REG_INVALID:
                base_val = state.register(mem.base)
                if base_val.is_exact:
                    eff = (base_val.exact_value + mem.disp) & 0xFFFF_FFFF
                    try:
                        raw = self.image.read(eff, decoded.operands[0].size)
                        if decoded.operands[0].size == 4:
                            val = int.from_bytes(raw, "little")
                            return state.with_register(
                                decoded.operands[0].reg,
                                _exact(val, origin=f"mem:{eff:#x}"),
                            )
                    except ValueError:
                        pass
            return state.with_register(
                decoded.operands[0].reg,
                _unknown(origin=f"complex-mem:{address:#x}"),
            )

        # MOV [mem], reg -- stores not tracked locally
        if (
            decoded.id == X86_INS_MOV
            and len(decoded.operands) == 2
            and decoded.operands[0].type == X86_OP_MEM
        ):
            return state

        # MOVZX / MOVSX
        if decoded.id in {X86_INS_MOVZX, X86_INS_MOVSX}:
            if len(decoded.operands) >= 2 and decoded.operands[0].type == X86_OP_REG:
                src = state.register(decoded.operands[1].reg)
                return state.with_register(decoded.operands[0].reg, src)

        # LEA reg, [base + disp]
        if decoded.id == X86_INS_LEA:
            if len(decoded.operands) == 2 and decoded.operands[0].type == X86_OP_REG:
                mem = decoded.operands[1].mem
                if mem.base != X86_REG_INVALID and mem.index == X86_REG_INVALID:
                    base = state.register(mem.base)
                    if base.is_exact:
                        eff = (base.exact_value + mem.disp) & 0xFFFF_FFFF
                        return state.with_register(
                            decoded.operands[0].reg,
                            _exact(eff, origin=f"lea:{address:#x}"),
                        )
                if mem.base == X86_REG_INVALID and mem.index == X86_REG_INVALID:
                    return state.with_register(
                        decoded.operands[0].reg,
                        _exact(mem.disp & 0xFFFF_FFFF, origin=f"lea:{address:#x}"),
                    )

        # PUSH, arithmetic -- preserve state (conservative)
        return state


# ── Main analysis entry point ──────────────────────────────────────────────


def analyze_values(
    image: Image,
    cfg: RawCfg,
    control_targets: ControlTargetResult,
    roots: Sequence[int] = (),
    limits: AnalysisLimits | None = None,
) -> AnalysisResult:
    """Run bounded interprocedural abstract interpretation to fixed point.

    Args:
        image: Strict PE image.
        cfg: Raw CFG from Task 4.
        control_targets: Task 4 control-target result (finite edges,
            terminal externals, unresolved).  Must be preserved
            monotonically.
        roots: Additional function entries to analyze (beyond those in
            cfg.function_entries).  Default empty.
        limits: Analysis caps.  Uses ``AnalysisLimits.for_image(image)``
            when None.
    """
    if limits is None:
        limits = AnalysisLimits.for_image(image)

    xfer = _TransferFunctions(image, cfg)

    # ── Build function entries ──────────────────────────────
    function_entries: set[int] = {e.address for e in cfg.function_entries}
    for root in roots:
        function_entries.add(root)

    # ── Build call graph from direct calls + finite targets ─
    call_graph: dict[int, set[int]] = defaultdict(set)
    for call in cfg.direct_calls:
        owner = _owning_function(cfg, call.address)
        if owner is not None and call.target in function_entries:
            call_graph.setdefault(owner, set()).add(call.target)

    for edge in control_targets.finite_internal_edges:
        owner = _owning_function(cfg, edge.source)
        if owner is not None:
            call_graph.setdefault(owner, set()).add(edge.target)

    # ── SCC decomposition ───────────────────────────────────
    sccs = _compute_sccs(function_entries, call_graph)
    scc_order = _topological_scc_order(sccs, call_graph)

    summaries: dict[int, FunctionSummary] = {}
    scc_iterations = 0
    update_count = 0

    for scc in scc_order:
        scc_iterations += 1
        limits.check("max_scc_iterations", scc_iterations)

        entries = sorted(scc)
        for entry in entries:
            if entry not in summaries:
                summaries[entry] = FunctionSummary.empty(entry)

        changed = True
        local_iterations = 0
        while changed:
            local_iterations += 1
            limits.check("max_summary_iterations", local_iterations)
            changed = False
            for entry in entries:
                old = summaries[entry]
                new = _compute_summary(
                    image, cfg, xfer, entry, summaries, limits
                )
                update_count += 1
                limits.check("max_fixpoint_updates", update_count)
                if new != old:
                    summaries[entry] = new
                    changed = True

    return AnalysisResult(
        compiler_sha256=image.sha256,
        cfg_instruction_hash=_cfg_instruction_hash(cfg),
        summaries=tuple(summaries[e] for e in sorted(summaries)),
        proof_ready=True,
        limits=limits,
        high_water_marks=(
            ("scc_iterations", scc_iterations),
            ("max_fixpoint_updates", update_count),
        ),
    )


def _compute_summary(
    image: Image,
    cfg: RawCfg,
    xfer: _TransferFunctions,
    entry: int,
    summaries: dict[int, FunctionSummary],
    limits: AnalysisLimits,
) -> FunctionSummary:
    """Intraprocedural abstract interpretation over one function's blocks."""
    func_blocks = [
        b for b in cfg.blocks
        if _owning_function(cfg, b.start) == entry
    ]
    if not func_blocks:
        return FunctionSummary.empty(entry)

    state = MachineState.empty()
    block_states: dict[int, MachineState] = {}
    worklist = [min(b.start for b in func_blocks)]
    visited: set[int] = set()
    iterations = 0

    while worklist:
        iterations += 1
        if iterations > 100_000:
            break
        block_addr = worklist.pop()
        if block_addr in visited:
            continue
        visited.add(block_addr)
        state = block_states.get(block_addr, MachineState.empty())

        # Execute all instructions in this block
        for insn_addr in _block_addresses(cfg, block_addr):
            state = xfer.eval(state, insn_addr)

        # Propagate to successors
        for edge in cfg.edges:
            if edge.source == _block_end(cfg, block_addr):
                if edge.kind.endswith("fallthrough") or "branch" in edge.kind:
                    existing = block_states.get(edge.target)
                    if existing is None:
                        block_states[edge.target] = state
                        worklist.append(edge.target)
                    else:
                        joined = _join_states(existing, state)
                        if joined != existing:
                            block_states[edge.target] = joined
                            worklist.append(edge.target)

    # Collect callees
    callees: set[int] = set()
    for block in func_blocks:
        for edge in cfg.edges:
            if edge.kind == "direct-call" and _block_contains(cfg, block.start, edge.source):
                callees.add(edge.target)

    return FunctionSummary(
        entry=entry,
        callees=tuple(sorted(callees)),
    )


def _block_addresses(cfg: RawCfg, block_start: int) -> list[int]:
    for block in cfg.blocks:
        if block.start == block_start:
            return list(block.instruction_addresses)
    return []


def _block_contains(cfg: RawCfg, block_start: int, address: int) -> bool:
    return address in _block_addresses(cfg, block_start)


def _join_states(a: MachineState, b: MachineState) -> MachineState:
    max_len = max(len(a.registers), len(b.registers))
    regs = []
    for i in range(max_len):
        regs.append(a.register(i).join(b.register(i)))
    return MachineState(registers=tuple(regs), stack_locals=a.stack_locals)


def _cfg_instruction_hash(cfg: RawCfg) -> str:
    import hashlib
    return hashlib.sha256(
        b"".join(bytes.fromhex(r.bytes_hex) for r in cfg.instructions)
    ).hexdigest()


def _compute_sccs(
    nodes: set[int], edges: dict[int, set[int]]
) -> list[set[int]]:
    """Kosaraju's SCC algorithm."""
    visited: set[int] = set()
    order: list[int] = []

    for node in sorted(nodes):
        if node not in visited:
            stack: list[tuple[int, int]] = [(node, 0)]
            while stack:
                n, state = stack.pop()
                if state == 0:
                    if n in visited:
                        continue
                    visited.add(n)
                    stack.append((n, 1))
                    for succ in sorted(edges.get(n, set())):
                        if succ not in visited:
                            stack.append((succ, 0))
                else:
                    order.append(n)

    reversed_edges: dict[int, set[int]] = defaultdict(set)
    for src, targets in edges.items():
        for tgt in targets:
            reversed_edges.setdefault(tgt, set()).add(src)

    sccs: list[set[int]] = []
    visited.clear()

    for node in reversed(order):
        if node not in visited:
            scc: set[int] = set()
            stack = [node]
            while stack:
                n = stack.pop()
                if n in visited:
                    continue
                visited.add(n)
                scc.add(n)
                for succ in sorted(reversed_edges.get(n, set())):
                    if succ not in visited:
                        stack.append(succ)
            sccs.append(scc)

    return sccs


def _topological_scc_order(
    sccs: list[set[int]], edges: dict[int, set[int]]
) -> list[set[int]]:
    scc_map: dict[int, int] = {}
    for i, scc in enumerate(sccs):
        for node in scc:
            scc_map[node] = i

    scc_edges: dict[int, set[int]] = defaultdict(set)
    for src, targets in edges.items():
        if src in scc_map:
            for tgt in targets:
                if tgt in scc_map and scc_map[src] != scc_map[tgt]:
                    scc_edges.setdefault(scc_map[src], set()).add(scc_map[tgt])

    in_degree = {i: 0 for i in range(len(sccs))}
    for src, targets in scc_edges.items():
        for tgt in targets:
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue = [i for i in range(len(sccs)) if in_degree.get(i, 0) == 0]
    result: list[set[int]] = []
    while queue:
        node = queue.pop(0)
        result.append(sccs[node])
        for succ in scc_edges.get(node, set()):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    return result
