"""Bounded interprocedural values and types for the retail compiler CFG.

Task 4 closes control targets.  This module consumes that exact result and
adds semantic facts monotonically: symbolic cdecl arguments, finite integers,
affine allocation sizes, stack/global values, typed pointers, call summaries,
and memory writes.  Every worklist is bounded by :class:`AnalysisLimits`; no
wall-clock or implicit iteration escape is used.
"""

from __future__ import annotations

import hashlib
import heapq
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from capstone import CS_ARCH_X86, CS_GRP_CALL, CS_GRP_RET, CS_MODE_32, Cs
from capstone.x86 import (
    X86_INS_ADD,
    X86_INS_AND,
    X86_INS_CMP,
    X86_INS_DEC,
    X86_INS_IMUL,
    X86_INS_INC,
    X86_INS_JE,
    X86_INS_JNE,
    X86_INS_LEA,
    X86_INS_MOV,
    X86_INS_MOVSX,
    X86_INS_MOVZX,
    X86_INS_OR,
    X86_INS_POP,
    X86_INS_PUSH,
    X86_INS_SAL,
    X86_INS_SHL,
    X86_INS_SUB,
    X86_INS_TEST,
    X86_INS_XOR,
    X86_OP_IMM,
    X86_OP_MEM,
    X86_OP_REG,
    X86_REG_EAX,
    X86_REG_EBP,
    X86_REG_EBX,
    X86_REG_ECX,
    X86_REG_EDI,
    X86_REG_EDX,
    X86_REG_ESI,
    X86_REG_ESP,
    X86_REG_INVALID,
)
from capstone.x86_const import (
    X86_EFLAGS_MODIFY_ZF,
    X86_EFLAGS_RESET_ZF,
    X86_EFLAGS_SET_ZF,
    X86_EFLAGS_UNDEFINED_ZF,
)

from tools.mwcc_retro.pe import Image
from tools.mwcc_retro.x86_cfg import (
    AnalysisLimits,
    ControlTargetResult,
    RawCfg,
)

_MASK32 = 0xFFFF_FFFF
_REGISTER_COUNT = 256
_ARGUMENT_SLOTS = 32
_CALL_ARGUMENT_SLOTS = 16
_ARENA_ALLOCATORS = frozenset({0x00441F20, 0x00441F60, 0x00441FA0, 0x00441FE0})
_PCODE_CONSTRUCTORS = frozenset({0x004A25D0, 0x004A2620, 0x004A2660, 0x0049D270})
_PCODE_ALLOCATION_CALLS = frozenset(
    {0x004636DE, 0x0046374D, 0x00463770, 0x0049D29A, 0x0049D2AF, 0x004A26CF}
)
_FUNCTION_ARGUMENT_TYPES: dict[int, dict[int, str]] = {
    0x00463640: {0: "objobject"},
    0x0049D270: {0: "pcode"},
    0x004BC7B0: {0: "objobject"},
}
_IDENTITY_POINTER_HELPERS = frozenset({0x004C1720})
_SYMBOLIC_RETURN_HELPERS = {
    0x004BC7B0: "objobject-pcode-extra-operand-count",
}


@dataclass(frozen=True, slots=True)
class AbstractValue:
    """One canonical element of the finite value/type lattice."""

    kind: str = "bottom"
    values: frozenset[int] = frozenset()
    affine_base: int = 0
    affine_stride: int = 0
    affine_symbol: str = ""
    affine_terms: tuple[tuple[str, int], ...] = ()
    pointer_base: int = 0
    pointer_offset: int = 0
    pointer_type: str = ""
    allocation_site: int | None = None
    origin: str = ""

    @property
    def is_bottom(self) -> bool:
        return self.kind == "bottom"

    @property
    def is_exact(self) -> bool:
        return self.kind in {"exact", "null"} and len(self.values) == 1

    @property
    def exact_value(self) -> int | None:
        return next(iter(self.values)) if self.is_exact else None

    @property
    def is_unknown(self) -> bool:
        return self.kind == "unknown"

    @property
    def is_finite(self) -> bool:
        return self.kind in {"exact", "finite", "null"}

    @property
    def affine(self) -> tuple[int, int, str] | None:
        if self.kind not in {"affine", "argument"}:
            return None
        if self.affine_terms:
            if len(self.affine_terms) != 1:
                return None
            symbol, stride = self.affine_terms[0]
            return self.affine_base, stride, symbol
        return self.affine_base, self.affine_stride, self.affine_symbol

    def with_offset(self, delta: int, origin: str) -> AbstractValue:
        if self.kind == "pointer":
            return AbstractValue(
                kind="pointer",
                pointer_base=self.pointer_base,
                pointer_offset=self.pointer_offset + delta,
                pointer_type=self.pointer_type,
                allocation_site=self.allocation_site,
                origin=origin,
            )
        if self.kind in {"argument", "affine"}:
            return _linear(
                self.affine_base + delta,
                _terms(self),
                origin,
            )
        if self.is_finite:
            return _finite(
                ((value + delta) & _MASK32 for value in self.values), origin
            )
        return _unknown(f"{origin}:add-to-{self.kind}")

    def scaled(self, scale: int, origin: str) -> AbstractValue:
        if self.kind in {"argument", "affine"}:
            return _linear(
                self.affine_base * scale,
                ((symbol, coefficient * scale) for symbol, coefficient in _terms(self)),
                origin,
            )
        if self.is_finite:
            return _finite(
                ((value * scale) & _MASK32 for value in self.values), origin
            )
        return _unknown(f"{origin}:scale-{self.kind}")

    def substitute(
        self, arguments: tuple[AbstractValue, ...], origin: str
    ) -> AbstractValue:
        if self.kind not in {"argument", "affine"}:
            return self
        result = _exact(self.affine_base, origin)
        for symbol, coefficient in _terms(self):
            value: AbstractValue
            if symbol.startswith("arg") and symbol[3:].isdigit():
                index = int(symbol[3:])
                if index >= len(arguments):
                    return _unknown(f"{origin}:missing-argument-{index}")
                value = arguments[index]
            else:
                value = _linear(0, ((symbol, 1),), origin)
            result = _add_values(result, value.scaled(coefficient, origin), origin)
        return result

    def join(self, other: AbstractValue) -> AbstractValue:
        if self.is_bottom:
            return other
        if other.is_bottom:
            return self
        if self == other:
            return self
        if self.is_unknown:
            return self
        if other.is_unknown:
            return other
        if self.is_finite and other.is_finite:
            merged = self.values | other.values
            return _finite(
                merged,
                "join:finite:" + ",".join(f"{row:#x}" for row in sorted(merged)),
            )
        if (
            self.kind in {"argument", "affine"}
            and other.is_finite
        ) or (
            other.kind in {"argument", "affine"}
            and self.is_finite
        ):
            return _affine_choice(self, other)
        if (
            self.kind in {"argument", "affine"}
            and other.kind in {"argument", "affine"}
            and self.affine_base == other.affine_base
            and _terms(self) == _terms(other)
        ):
            return _linear(
                self.affine_base,
                _terms(self),
                f"join:affine:{self.affine_base}:{_terms(self)!r}",
            )
        if self.kind in {"argument", "affine"} and other.kind in {
            "argument",
            "affine",
        }:
            return _affine_choice(self, other)
        if (
            self.kind == other.kind == "pointer"
            and self.pointer_base == other.pointer_base
            and self.pointer_offset == other.pointer_offset
            and self.pointer_type == other.pointer_type
            and self.allocation_site == other.allocation_site
        ):
            return AbstractValue(
                kind="pointer",
                pointer_base=self.pointer_base,
                pointer_offset=self.pointer_offset,
                pointer_type=self.pointer_type,
                allocation_site=self.allocation_site,
                origin=(
                    f"join:pointer:{self.pointer_type}:{self.pointer_base:#x}:"
                    f"{self.pointer_offset:#x}:{self.allocation_site}"
                ),
            )
        if {self.kind, other.kind} == {"null", "pointer"}:
            return _unknown(_join_origin(self, other, "nullable-pointer"))
        return _unknown(_join_origin(self, other))


_BOTTOM = AbstractValue()


def _exact(value: int, origin: str) -> AbstractValue:
    value &= _MASK32
    return AbstractValue(
        kind="null" if value == 0 else "exact",
        values=frozenset({value}),
        origin=origin,
    )


def _finite(values: Iterable[int], origin: str) -> AbstractValue:
    frozen = frozenset(value & _MASK32 for value in values)
    if not frozen:
        return _BOTTOM
    return AbstractValue(
        kind="exact" if len(frozen) == 1 else "finite",
        values=frozen,
        origin=origin,
    )


def _unknown(origin: str) -> AbstractValue:
    return AbstractValue(kind="unknown", origin=origin)


def _argument(index: int) -> AbstractValue:
    return AbstractValue(
        kind="argument",
        affine_stride=1,
        affine_symbol=f"arg{index}",
        affine_terms=((f"arg{index}", 1),),
        origin=f"formal-argument:{index}",
    )


def _terms(value: AbstractValue) -> tuple[tuple[str, int], ...]:
    if value.affine_terms:
        return value.affine_terms
    if value.affine_symbol:
        return ((value.affine_symbol, value.affine_stride),)
    return ()


def _linear(
    base: int,
    terms: Iterable[tuple[str, int]],
    origin: str,
) -> AbstractValue:
    combined: dict[str, int] = defaultdict(int)
    for symbol, coefficient in terms:
        combined[symbol] += coefficient
    canonical = tuple(
        (symbol, coefficient)
        for symbol, coefficient in sorted(combined.items())
        if coefficient
    )
    if not canonical:
        return _exact(base, origin)
    symbol = canonical[0][0] if len(canonical) == 1 else ""
    stride = canonical[0][1] if len(canonical) == 1 else 0
    return AbstractValue(
        kind="affine",
        affine_base=base,
        affine_stride=stride,
        affine_symbol=symbol,
        affine_terms=canonical,
        origin=origin,
    )


def _pointer(
    pointer_type: str,
    base: int,
    offset: int,
    origin: str,
    allocation_site: int | None = None,
) -> AbstractValue:
    return AbstractValue(
        kind="pointer",
        pointer_base=base,
        pointer_offset=offset,
        pointer_type=pointer_type,
        allocation_site=allocation_site,
        origin=origin,
    )


def _join_origin(
    left: AbstractValue, right: AbstractValue, reason: str = "incompatible"
) -> str:
    kinds = ",".join(sorted((left.kind, right.kind)))
    return f"join:{reason}:{kinds}"


@dataclass(frozen=True, slots=True)
class MachineState:
    """Public frozen state snapshot used by fixtures and reports."""

    registers: tuple[AbstractValue, ...]
    stack_locals: tuple[tuple[int, AbstractValue], ...] = ()
    esp_offset: int | None = 0
    ebp_offset: int | None = None

    @staticmethod
    def empty() -> MachineState:
        return MachineState(tuple(_BOTTOM for _ in range(_REGISTER_COUNT)))

    def register(self, reg_id: int) -> AbstractValue:
        return self.registers[reg_id] if 0 <= reg_id < len(self.registers) else _BOTTOM

    def stack_local(self, offset: int) -> AbstractValue:
        return dict(self.stack_locals).get(offset, _BOTTOM)

    def with_register(self, reg_id: int, value: AbstractValue) -> MachineState:
        registers = list(self.registers)
        while len(registers) <= reg_id:
            registers.append(_BOTTOM)
        registers[reg_id] = value
        return MachineState(
            tuple(registers), self.stack_locals, self.esp_offset, self.ebp_offset
        )

    def with_stack_local(self, offset: int, value: AbstractValue) -> MachineState:
        stack = dict(self.stack_locals)
        stack[offset] = value
        return MachineState(
            self.registers,
            tuple(sorted(stack.items())),
            self.esp_offset,
            self.ebp_offset,
        )


@dataclass(frozen=True, slots=True)
class CallFact:
    address: int
    target: int
    function_entry: int
    arguments: tuple[AbstractValue, ...]
    return_value: AbstractValue

    def argument(self, index: int) -> AbstractValue:
        return self.arguments[index] if index < len(self.arguments) else _BOTTOM


@dataclass(frozen=True, slots=True)
class MemoryWriteFact:
    address: int
    function_entry: int
    width: int
    base: AbstractValue
    offset: int
    value: AbstractValue
    operation: str


@dataclass(frozen=True, slots=True)
class AllocationFact:
    call_address: int
    allocator: int
    size: AbstractValue
    returned_type: str


@dataclass(frozen=True, slots=True)
class UnresolvedValue:
    address: int
    kind: str
    reason: str
    origin: str = ""


@dataclass(frozen=True, slots=True)
class FunctionSummary:
    entry: int
    argument_flows: tuple[tuple[int, AbstractValue], ...] = ()
    allocations: tuple[AllocationFact, ...] = ()
    typed_writes: tuple[MemoryWriteFact, ...] = ()
    return_value: AbstractValue = field(default_factory=lambda: _BOTTOM)
    callees: tuple[int, ...] = ()

    @staticmethod
    def empty(entry: int) -> FunctionSummary:
        return FunctionSummary(entry=entry)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    compiler_sha256: str
    cfg_instruction_hash: str
    summaries: tuple[FunctionSummary, ...]
    calls: tuple[CallFact, ...]
    memory_writes: tuple[MemoryWriteFact, ...]
    finite_internal_edges: tuple[Any, ...]
    terminal_external_edges: tuple[Any, ...]
    external_escapes: tuple[Any, ...]
    unresolved: tuple[UnresolvedValue, ...] = ()
    proof_ready: bool = False
    limits: AnalysisLimits | None = None
    high_water_marks: tuple[tuple[str, int], ...] = ()
    register_domains: tuple[Any, ...] = ()
    custom_opcode_layouts_proved: bool = False
    variadic_bounds_proved: bool = False

    def summary_at(self, address: int) -> FunctionSummary | None:
        return next((row for row in self.summaries if row.entry == address), None)

    def call_at(self, address: int) -> CallFact:
        rows = tuple(row for row in self.calls if row.address == address)
        if not rows:
            raise KeyError(f"no call fact at {address:#x}")
        if len({(row.target, row.function_entry) for row in rows}) != 1:
            raise KeyError(f"call paths disagree on target or owner at {address:#x}")
        arguments = list(rows[0].arguments)
        returned = rows[0].return_value
        for row in rows[1:]:
            arguments = [
                left.join(right)
                for left, right in zip(arguments, row.arguments, strict=True)
            ]
            returned = returned.join(row.return_value)
        return CallFact(
            address,
            rows[0].target,
            rows[0].function_entry,
            tuple(arguments),
            returned,
        )

    def call_paths_at(self, address: int) -> tuple[CallFact, ...]:
        return tuple(row for row in self.calls if row.address == address)

    def writes_at(self, address: int) -> tuple[MemoryWriteFact, ...]:
        return tuple(row for row in self.memory_writes if row.address == address)


@dataclass
class _State:
    registers: dict[int, AbstractValue]
    stack: dict[int, AbstractValue]
    esp_offset: int | None
    ebp_offset: int | None
    zero_register: int | None

    @classmethod
    def entry(cls, function_entry: int) -> _State:
        stack: dict[int, AbstractValue] = {}
        typed = _FUNCTION_ARGUMENT_TYPES.get(function_entry, {})
        for index in range(_ARGUMENT_SLOTS):
            if index in typed:
                stack[4 + index * 4] = _pointer(
                    typed[index],
                    -(index + 1),
                    0,
                    f"formal-{typed[index]}-argument:{index}",
                )
            else:
                stack[4 + index * 4] = _argument(index)
        return cls(
            registers={},
            stack=stack,
            esp_offset=0,
            ebp_offset=None,
            zero_register=None,
        )

    def copy(self) -> _State:
        return _State(
            dict(self.registers),
            dict(self.stack),
            self.esp_offset,
            self.ebp_offset,
            self.zero_register,
        )

    def key(self) -> tuple[Any, ...]:
        return (
            tuple(sorted(self.registers.items())),
            tuple(sorted(self.stack.items())),
            self.esp_offset,
            self.ebp_offset,
            self.zero_register,
        )


@dataclass(frozen=True)
class _FunctionAnalysis:
    summary: FunctionSummary
    calls: tuple[CallFact, ...]
    writes: tuple[MemoryWriteFact, ...]
    unresolved: tuple[UnresolvedValue, ...]
    block_updates: int
    finite_value_high_water: int


class _Interpreter:
    def __init__(self, image: Image, cfg: RawCfg, limits: AnalysisLimits):
        self.image = image
        self.cfg = cfg
        self.limits = limits
        self.decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        self.decoder.detail = True
        self.instructions = {row.address: row for row in cfg.instructions}
        self.decoded: dict[int, Any] = {}
        self.blocks = {row.start: row for row in cfg.blocks}
        self.instruction_block = {
            address: block.start
            for block in cfg.blocks
            for address in block.instruction_addresses
        }
        self.direct_calls = {row.address: row.target for row in cfg.direct_calls}
        self.function_entries = tuple(sorted(row.address for row in cfg.function_entries))
        self.function_entry_set = set(self.function_entries)
        self.successor_edges = self._build_successors()
        self.successors = {
            source: tuple(sorted({target for target, _kind in edges}))
            for source, edges in self.successor_edges.items()
        }
        self.function_blocks = {
            entry: self._blocks_for_function(entry) for entry in self.function_entries
        }
        self.instruction_owner = self._build_instruction_owners()

    def _decode(self, address: int):
        if address not in self.decoded:
            row = self.instructions[address]
            raw = self.image.read(address, row.size)
            decoded = next(self.decoder.disasm(raw, address), None)
            if decoded is None or decoded.size != row.size:
                raise ValueError(f"cannot re-decode accepted instruction at {address:#x}")
            self.decoded[address] = decoded
        return self.decoded[address]

    def _build_successors(self) -> dict[int, tuple[tuple[int, str], ...]]:
        successors: dict[int, set[tuple[int, str]]] = defaultdict(set)
        for edge in self.cfg.edges:
            if edge.kind == "direct-call" or edge.kind.startswith("indirect-call"):
                continue
            target_block = self.instruction_block.get(edge.target, edge.target)
            if target_block in self.blocks:
                source_block = self.instruction_block.get(edge.source)
                if source_block is not None:
                    successors[source_block].add((target_block, edge.kind))
        return {
            source: tuple(sorted(targets)) for source, targets in successors.items()
        }

    def _blocks_for_function(self, entry: int) -> tuple[int, ...]:
        start = self.instruction_block.get(entry, entry)
        if start not in self.blocks:
            return ()
        found: set[int] = set()
        pending = [start]
        while pending:
            block = pending.pop()
            if block in found:
                continue
            if block != start and block in self.function_entry_set:
                continue
            found.add(block)
            pending.extend(reversed(self.successors.get(block, ())))
        return tuple(sorted(found))

    def _build_instruction_owners(self) -> dict[int, int]:
        candidates: dict[int, list[int]] = defaultdict(list)
        for entry, blocks in self.function_blocks.items():
            for block_start in blocks:
                for address in self.blocks[block_start].instruction_addresses:
                    candidates[address].append(entry)
        return {
            address: max(entries)
            for address, entries in candidates.items()
        }

    def call_graph(self) -> dict[int, set[int]]:
        graph: dict[int, set[int]] = defaultdict(set)
        for address, target in self.direct_calls.items():
            owner = self.instruction_owner.get(address)
            if owner is not None and target in self.function_entry_set:
                graph[owner].add(target)
        return graph

    def analyze_function(
        self, entry: int, summaries: dict[int, FunctionSummary]
    ) -> _FunctionAnalysis:
        owned = set(self.function_blocks.get(entry, ()))
        if not owned:
            return _FunctionAnalysis(
                FunctionSummary.empty(entry), (), (), (), 0, 0
            )
        start = self.instruction_block.get(entry, entry)
        incoming: dict[int, _State] = {start: _State.entry(entry)}
        pending = deque([start])
        pending_set = {start}
        calls: set[CallFact] = set()
        writes: set[MemoryWriteFact] = set()
        unresolved: set[UnresolvedValue] = set()
        returns: list[AbstractValue] = []
        allocations: set[AllocationFact] = set()
        updates = 0
        finite_high = 0
        state_updates: dict[int, int] = defaultdict(int)

        while pending:
            block_start = pending.popleft()
            pending_set.remove(block_start)
            state = incoming[block_start].copy()
            block = self.blocks[block_start]
            for address in block.instruction_addresses:
                decoded = self._decode(address)
                if decoded.group(CS_GRP_CALL):
                    fact, allocation = self._eval_call(
                        entry, state, address, summaries
                    )
                    calls.add(fact)
                    if allocation is not None:
                        allocations.add(allocation)
                    continue
                write = self._eval_instruction(entry, state, address, unresolved)
                if write is not None:
                    writes.add(write)
                if decoded.group(CS_GRP_RET):
                    returns.append(state.registers.get(X86_REG_EAX, _BOTTOM))

            last_decoded = self._decode(block.instruction_addresses[-1])
            for successor, edge_kind in self.successor_edges.get(block_start, ()):
                if successor not in owned:
                    continue
                successor_state = _refine_branch_state(
                    state, last_decoded.id, edge_kind
                )
                if successor_state is None:
                    continue
                prior = incoming.get(successor)
                if prior is None:
                    incoming[successor] = successor_state
                    changed = True
                else:
                    joined, _finite_count_before_widen = _join_states(
                        prior, successor_state
                    )
                    joined = _widen_finite_budget(
                        prior,
                        joined,
                        successor,
                        min(4_096, self.limits.max_finite_values - 1),
                    )
                    if state_updates[successor] >= min(
                        32, self.limits.max_states_per_block - 1
                    ):
                        joined = _widen_state(prior, joined, successor)
                    finite_count = _state_finite_count(joined)
                    finite_high = max(finite_high, finite_count)
                    self.limits.check("max_finite_values", finite_high)
                    changed = joined.key() != prior.key()
                    if changed:
                        incoming[successor] = joined
                if changed:
                    updates += 1
                    self.limits.check("max_fixpoint_updates", updates)
                    state_updates[successor] += 1
                    self.limits.check(
                        "max_states_per_block", state_updates[successor]
                    )
                    if successor not in pending_set:
                        pending.append(successor)
                        pending_set.add(successor)

        return_value = _BOTTOM
        for value in returns:
            return_value = return_value.join(value)
        callees = tuple(
            sorted(
                target
                for address, target in self.direct_calls.items()
                if self.instruction_owner.get(address) == entry
            )
        )
        typed_writes = tuple(
            sorted(
                (row for row in writes if row.base.pointer_type in {"pcode", "objobject"}),
                key=_write_key,
            )
        )
        summary = FunctionSummary(
            entry=entry,
            allocations=tuple(sorted(allocations, key=lambda row: row.call_address)),
            typed_writes=typed_writes,
            return_value=return_value,
            callees=callees,
        )
        return _FunctionAnalysis(
            summary=summary,
            calls=tuple(sorted(calls, key=_call_key)),
            writes=tuple(sorted(writes, key=_write_key)),
            unresolved=tuple(sorted(unresolved, key=_unresolved_key)),
            block_updates=updates,
            finite_value_high_water=finite_high,
        )

    def _eval_call(
        self,
        entry: int,
        state: _State,
        address: int,
        summaries: dict[int, FunctionSummary],
    ) -> tuple[CallFact, AllocationFact | None]:
        target = self.direct_calls.get(address, 0)
        arguments = tuple(
            state.stack.get(
                (state.esp_offset or 0) + index * 4,
                _BOTTOM,
            )
            for index in range(_CALL_ARGUMENT_SLOTS)
        )
        allocation: AllocationFact | None = None
        if target in _ARENA_ALLOCATORS:
            size = arguments[0]
            returned_type = (
                "pcode" if address in _PCODE_ALLOCATION_CALLS else "arena-allocation"
            )
            returned = _pointer(
                returned_type, address, 0, f"arena-call:{address:#x}", address
            )
            allocation = AllocationFact(address, target, size, returned_type)
        elif target in _PCODE_CONSTRUCTORS:
            returned = _pointer(
                "pcode", address, 0, f"pcode-call:{address:#x}", address
            )
        elif target in _IDENTITY_POINTER_HELPERS:
            returned = arguments[0]
        elif target in _SYMBOLIC_RETURN_HELPERS:
            argument = arguments[0]
            if argument.is_bottom or argument.is_unknown:
                returned = _unknown(
                    f"symbolic-helper-argument:{address:#x}:{target:#x}:"
                    f"{argument.origin}"
                )
            else:
                returned = _linear(
                    0,
                    ((
                        f"{_SYMBOLIC_RETURN_HELPERS[target]}"
                        f"[{_value_expression(argument)}]",
                        1,
                    ),),
                    f"symbolic-helper-return:{address:#x}:{target:#x}",
                )
        elif target in summaries:
            returned = summaries[target].return_value.substitute(
                arguments, f"call:{address:#x}"
            )
        else:
            returned = _unknown(f"unmodelled-call-return:{address:#x}:{target:#x}")

        for register in (X86_REG_EAX, X86_REG_ECX, X86_REG_EDX):
            state.registers.pop(register, None)
        state.registers[X86_REG_EAX] = returned
        state.zero_register = None
        return CallFact(address, target, entry, arguments, returned), allocation

    def _eval_instruction(
        self,
        entry: int,
        state: _State,
        address: int,
        unresolved: set[UnresolvedValue],
    ) -> MemoryWriteFact | None:
        insn = self._decode(address)
        operands = insn.operands
        if not operands:
            return None

        if insn.id == X86_INS_PUSH:
            value = self._read_operand(state, operands[0], address)
            if state.esp_offset is None:
                unresolved.add(
                    UnresolvedValue(address, "stack", "push-with-unknown-esp")
                )
            else:
                state.esp_offset -= 4
                state.stack[state.esp_offset] = value
            return None
        if insn.id == X86_INS_POP:
            value = _unknown(f"pop-unknown-stack:{address:#x}")
            if state.esp_offset is not None:
                value = state.stack.get(state.esp_offset, _BOTTOM)
                state.esp_offset += 4
            self._write_operand(state, operands[0], value, address)
            return None

        if insn.id in {X86_INS_MOV, X86_INS_MOVZX, X86_INS_MOVSX} and len(operands) == 2:
            value = self._read_operand(state, operands[1], address)
            if insn.id in {X86_INS_MOVZX, X86_INS_MOVSX}:
                value = _extend_value(
                    value,
                    operands[1].size,
                    signed=insn.id == X86_INS_MOVSX,
                    origin=f"extend:{address:#x}",
                )
            write = self._write_operand(
                state, operands[0], value, address, entry=entry, operation=insn.mnemonic
            )
            if (
                write is not None
                and write.base.pointer_type in {"pcode", "objobject"}
                and (write.value.is_bottom or write.value.is_unknown)
            ):
                unresolved.add(
                    UnresolvedValue(
                        address,
                        "typed-field-write",
                        f"unknown-value-affects-{write.base.pointer_type}-store",
                        write.value.origin,
                    )
                )
            return write

        if insn.id == X86_INS_LEA and len(operands) == 2:
            value = self._effective_address(state, operands[1], address)
            self._write_operand(state, operands[0], value, address)
            return None

        if insn.id in {X86_INS_CMP, X86_INS_TEST} and len(operands) == 2:
            state.zero_register = None
            left, right = operands
            same_register_test = (
                insn.id == X86_INS_TEST
                and left.type == right.type == X86_OP_REG
                and _canonical_register(insn, left.reg)
                == _canonical_register(insn, right.reg)
            )
            compare_register_to_zero = (
                insn.id == X86_INS_CMP
                and left.type == X86_OP_REG
                and right.type == X86_OP_IMM
                and right.imm == 0
            )
            if same_register_test or compare_register_to_zero:
                state.zero_register = _canonical_register(insn, left.reg)
            return None

        if insn.id in {
            X86_INS_ADD,
            X86_INS_SUB,
            X86_INS_IMUL,
            X86_INS_AND,
            X86_INS_OR,
            X86_INS_XOR,
            X86_INS_SHL,
            X86_INS_SAL,
        } and len(operands) >= 2:
            left_operand = (
                operands[1]
                if insn.id == X86_INS_IMUL and len(operands) == 3
                else operands[0]
            )
            left = self._read_operand(state, left_operand, address)
            right_operand = operands[-1]
            right = self._read_operand(state, right_operand, address)
            value = _binary_value(insn.id, left, right, address)
            write = self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )
            if operands[0].type == X86_OP_REG:
                state.zero_register = (
                    None
                    if insn.id == X86_INS_IMUL
                    else _canonical_register(insn, operands[0].reg)
                )
            return write

        if insn.id in {X86_INS_INC, X86_INS_DEC}:
            left = self._read_operand(state, operands[0], address)
            value = left.with_offset(
                1 if insn.id == X86_INS_INC else -1,
                f"{insn.mnemonic}:{address:#x}",
            )
            write = self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )
            if operands[0].type == X86_OP_REG:
                state.zero_register = _canonical_register(insn, operands[0].reg)
            return write

        if any(operand.type == X86_OP_MEM for operand in operands):
            for operand in operands:
                if operand.type != X86_OP_MEM:
                    continue
                base = self._effective_address(state, operand, address)
                if base.pointer_type in {"pcode", "objobject"}:
                    unresolved.add(
                        UnresolvedValue(
                            address,
                            "unsupported-instruction",
                            f"unsupported-{insn.mnemonic}-affects-{base.pointer_type}",
                            base.origin,
                        )
                    )
        if insn.eflags & (
            X86_EFLAGS_MODIFY_ZF
            | X86_EFLAGS_RESET_ZF
            | X86_EFLAGS_SET_ZF
            | X86_EFLAGS_UNDEFINED_ZF
        ):
            state.zero_register = None
        return None

    def _read_operand(self, state: _State, operand, address: int) -> AbstractValue:
        insn = self._decode(address)
        if operand.type == X86_OP_IMM:
            return _exact(operand.imm, f"immediate:{address:#x}")
        if operand.type == X86_OP_REG:
            register = _canonical_register(insn, operand.reg)
            if register == X86_REG_ESP:
                if state.esp_offset is None:
                    return _unknown(f"esp:{address:#x}")
                return _pointer("stack", 0, state.esp_offset, f"esp:{address:#x}")
            if register == X86_REG_EBP and state.ebp_offset is not None:
                return _pointer("stack", 0, state.ebp_offset, f"ebp:{address:#x}")
            value = state.registers.get(register, _BOTTOM)
            return _truncate_value(value, operand.size, f"reg-read:{address:#x}")
        if operand.type == X86_OP_MEM:
            pointer = self._effective_address(state, operand, address)
            if pointer.pointer_type == "stack":
                return state.stack.get(pointer.pointer_offset, _BOTTOM)
            if pointer.pointer_type == "image":
                absolute = pointer.pointer_base + pointer.pointer_offset
                section = next(
                    (
                        row
                        for row in self.image.sections
                        if row.va <= absolute < row.va + row.mapped_size
                    ),
                    None,
                )
                if section is not None and section.characteristics & 0x80000000:
                    return _linear(
                        0,
                        ((f"global[{absolute:#x}]:u{operand.size * 8}", 1),),
                        f"mutable-global-read:{address:#x}",
                    )
                try:
                    payload = self.image.read(absolute, operand.size)
                except ValueError:
                    return _unknown(f"unmapped-image-read:{address:#x}:{absolute:#x}")
                return _exact(
                    int.from_bytes(payload, "little"),
                    f"image-read:{address:#x}:{absolute:#x}",
                )
            if pointer.kind in {"argument", "affine"}:
                expression = _linear_expression(pointer)
                return _linear(
                    0,
                    ((f"memory[{expression}]:u{operand.size * 8}", 1),),
                    f"symbolic-read:{address:#x}",
                )
            if pointer.kind == "pointer":
                return _linear(
                    0,
                    ((
                        f"{pointer.pointer_type}[{pointer.pointer_base}]"
                        f"{pointer.pointer_offset:+#x}:u{operand.size * 8}",
                        1,
                    ),),
                    f"typed-read:{address:#x}",
                )
        return _unknown(f"unsupported-operand-read:{address:#x}")

    def _write_operand(
        self,
        state: _State,
        operand,
        value: AbstractValue,
        address: int,
        *,
        entry: int | None = None,
        operation: str = "write",
    ) -> MemoryWriteFact | None:
        insn = self._decode(address)
        if operand.type == X86_OP_REG:
            register = _canonical_register(insn, operand.reg)
            if register == X86_REG_ESP:
                state.esp_offset = (
                    value.pointer_offset
                    if value.kind == "pointer" and value.pointer_type == "stack"
                    else None
                )
                return None
            if register == X86_REG_EBP:
                state.ebp_offset = (
                    value.pointer_offset
                    if value.kind == "pointer" and value.pointer_type == "stack"
                    else None
                )
            state.registers[register] = _write_width(
                state.registers.get(register, _BOTTOM),
                value,
                operand.size,
                f"reg-write:{address:#x}",
            )
            return None
        if operand.type == X86_OP_MEM:
            pointer = self._effective_address(state, operand, address)
            if pointer.pointer_type == "stack":
                state.stack[pointer.pointer_offset] = _truncate_value(
                    value, operand.size, f"stack-write:{address:#x}"
                )
                return None
            return MemoryWriteFact(
                address=address,
                function_entry=entry or 0,
                width=operand.size,
                base=pointer,
                offset=pointer.pointer_offset,
                value=_truncate_value(value, operand.size, f"mem-write:{address:#x}"),
                operation=operation,
            )
        return None

    def _effective_address(self, state: _State, operand, address: int) -> AbstractValue:
        if operand.type != X86_OP_MEM:
            return _unknown(f"not-memory:{address:#x}")
        mem = operand.mem
        if mem.base == X86_REG_INVALID and mem.index == X86_REG_INVALID:
            absolute = mem.disp & _MASK32
            return _pointer("image", absolute, 0, f"absolute:{address:#x}")
        base = _exact(0, f"zero-base:{address:#x}")
        if mem.base != X86_REG_INVALID:
            fake = type("RegisterOperand", (), {"type": X86_OP_REG, "reg": mem.base, "size": 4})
            base = self._read_operand(state, fake, address)
        if mem.index != X86_REG_INVALID:
            fake = type("RegisterOperand", (), {"type": X86_OP_REG, "reg": mem.index, "size": 4})
            index = self._read_operand(state, fake, address).scaled(
                mem.scale, f"index:{address:#x}"
            )
            base = _add_values(base, index, f"indexed-address:{address:#x}")
        if base.is_exact and self.image.section_of_va(base.exact_value or 0) is not None:
            base = _pointer(
                "image",
                int(base.exact_value or 0),
                0,
                f"mapped-address:{address:#x}",
            )
        return base.with_offset(mem.disp, f"address:{address:#x}")


def _canonical_register(insn, register: int) -> int:
    name = insn.reg_name(register)
    families = {
        "al": X86_REG_EAX,
        "ah": X86_REG_EAX,
        "ax": X86_REG_EAX,
        "eax": X86_REG_EAX,
        "bl": X86_REG_EBX,
        "bh": X86_REG_EBX,
        "bx": X86_REG_EBX,
        "ebx": X86_REG_EBX,
        "cl": X86_REG_ECX,
        "ch": X86_REG_ECX,
        "cx": X86_REG_ECX,
        "ecx": X86_REG_ECX,
        "dl": X86_REG_EDX,
        "dh": X86_REG_EDX,
        "dx": X86_REG_EDX,
        "edx": X86_REG_EDX,
        "si": X86_REG_ESI,
        "esi": X86_REG_ESI,
        "di": X86_REG_EDI,
        "edi": X86_REG_EDI,
        "bp": X86_REG_EBP,
        "ebp": X86_REG_EBP,
        "sp": X86_REG_ESP,
        "esp": X86_REG_ESP,
    }
    return families.get(name, register)


def _truncate_value(value: AbstractValue, size: int, origin: str) -> AbstractValue:
    if size >= 4 or value.kind in {"pointer", "argument", "affine"}:
        return value
    if value.is_finite:
        return _finite((row & ((1 << (size * 8)) - 1) for row in value.values), origin)
    return value


def _extend_value(
    value: AbstractValue, size: int, *, signed: bool, origin: str
) -> AbstractValue:
    if not value.is_finite:
        return value
    bits = size * 8
    mask = (1 << bits) - 1
    sign = 1 << (bits - 1)
    rows = []
    for row in value.values:
        row &= mask
        if signed and row & sign:
            row |= _MASK32 ^ mask
        rows.append(row)
    return _finite(rows, origin)


def _write_width(
    old: AbstractValue,
    new: AbstractValue,
    size: int,
    origin: str,
) -> AbstractValue:
    if size >= 4:
        return new
    if old.is_exact and new.is_exact:
        mask = (1 << (size * 8)) - 1
        return _exact(
            ((old.exact_value or 0) & ~mask) | ((new.exact_value or 0) & mask),
            origin,
        )
    return _unknown(f"{origin}:partial-register-write")


def _add_values(
    left: AbstractValue, right: AbstractValue, origin: str
) -> AbstractValue:
    if right.is_exact:
        return left.with_offset(_signed32(right.exact_value or 0), origin)
    if left.is_exact:
        return right.with_offset(_signed32(left.exact_value or 0), origin)
    if left.kind in {"argument", "affine"} and right.is_finite:
        domain = ",".join(f"{row:#x}" for row in sorted(right.values))
        return _linear(
            left.affine_base,
            (*_terms(left), (f"finite{{{domain}}}", 1)),
            origin,
        )
    if right.kind in {"argument", "affine"} and left.is_finite:
        domain = ",".join(f"{row:#x}" for row in sorted(left.values))
        return _linear(
            right.affine_base,
            (*_terms(right), (f"finite{{{domain}}}", 1)),
            origin,
        )
    if left.kind in {"argument", "affine"} and right.kind in {
        "argument",
        "affine",
    }:
        return _linear(
            left.affine_base + right.affine_base,
            (*_terms(left), *_terms(right)),
            origin,
        )
    if left.is_finite and right.is_finite:
        return _finite(
            (a + b for a in left.values for b in right.values), origin
        )
    return _unknown(f"{origin}:non-affine-add")


def _binary_value(
    instruction_id: int,
    left: AbstractValue,
    right: AbstractValue,
    address: int,
) -> AbstractValue:
    origin = f"binary:{address:#x}"
    if instruction_id == X86_INS_ADD:
        return _add_values(left, right, origin)
    if instruction_id == X86_INS_SUB:
        if right.is_exact:
            return left.with_offset(-_signed32(right.exact_value or 0), origin)
        if right.kind in {"argument", "affine"}:
            return _add_values(left, right.scaled(-1, origin), origin)
    if instruction_id == X86_INS_IMUL and right.is_exact:
        return left.scaled(_signed32(right.exact_value or 0), origin)
    if (
        instruction_id in {X86_INS_SHL, X86_INS_SAL}
        and right.is_exact
        and left.kind in {"argument", "affine"}
    ):
        return left.scaled(1 << ((right.exact_value or 0) & 0x1F), origin)
    if (
        instruction_id == X86_INS_AND
        and right.is_exact
        and left.kind in {"argument", "affine"}
        and (right.exact_value or 0).bit_count() == 1
    ):
        return _finite((0, right.exact_value or 0), origin)
    if instruction_id == X86_INS_XOR and left == right:
        return _exact(0, origin)
    if left.is_finite and right.is_finite:
        operator = {
            X86_INS_AND: lambda a, b: a & b,
            X86_INS_OR: lambda a, b: a | b,
            X86_INS_XOR: lambda a, b: a ^ b,
            X86_INS_SHL: lambda a, b: a << b,
            X86_INS_SAL: lambda a, b: a << b,
        }.get(instruction_id)
        if operator is not None:
            return _finite(
                (operator(a, b) for a in left.values for b in right.values), origin
            )
    return _unknown(f"{origin}:unsupported-value-operation")


def _signed32(value: int) -> int:
    value &= _MASK32
    return value - (1 << 32) if value & (1 << 31) else value


def _join_states(left: _State, right: _State) -> tuple[_State, int]:
    registers = {
        register: left.registers.get(register, _BOTTOM).join(
            right.registers.get(register, _BOTTOM)
        )
        for register in set(left.registers) | set(right.registers)
    }
    stack = {
        offset: left.stack.get(offset, _BOTTOM).join(right.stack.get(offset, _BOTTOM))
        for offset in set(left.stack) | set(right.stack)
    }
    finite_count = sum(
        len(value.values)
        for value in (*registers.values(), *stack.values())
        if value.is_finite
    )
    return (
        _State(
            registers,
            stack,
            left.esp_offset if left.esp_offset == right.esp_offset else None,
            left.ebp_offset if left.ebp_offset == right.ebp_offset else None,
            left.zero_register
            if left.zero_register == right.zero_register
            else None,
        ),
        finite_count,
    )


def _widen_state(prior: _State, joined: _State, block: int) -> _State:
    """Deterministically widen loop-variant finite values to named unknowns."""

    result = joined.copy()
    for register, value in tuple(result.registers.items()):
        before = prior.registers.get(register, _BOTTOM)
        if value != before and (value.is_finite or value.kind in {"affine", "argument"}):
            result.registers[register] = _unknown(
                f"loop-widen:block={block:#x}:register={register}"
            )
    for offset, value in tuple(result.stack.items()):
        before = prior.stack.get(offset, _BOTTOM)
        if value != before and (value.is_finite or value.kind in {"affine", "argument"}):
            result.stack[offset] = _unknown(
                f"loop-widen:block={block:#x}:stack={offset}"
            )
    return result


def _state_finite_count(state: _State) -> int:
    return sum(
        len(value.values)
        for value in (*state.registers.values(), *state.stack.values())
        if value.is_finite
    )


def _widen_finite_budget(
    prior: _State,
    joined: _State,
    block: int,
    budget: int,
) -> _State:
    """Keep finite joins bounded while retaining their exact widening origin."""

    result = joined.copy()
    candidates: list[tuple[int, str, int]] = []
    for register, value in result.registers.items():
        before = prior.registers.get(register, _BOTTOM)
        if value.is_finite and value != before:
            candidates.append((len(value.values), "register", register))
    for offset, value in result.stack.items():
        before = prior.stack.get(offset, _BOTTOM)
        if value.is_finite and value != before:
            candidates.append((len(value.values), "stack", offset))
    for size, location, key in sorted(candidates, reverse=True):
        if size <= 64 and _state_finite_count(result) < budget:
            break
        widened = _unknown(
            f"finite-widen:block={block:#x}:{location}={key}:values={size}"
        )
        if location == "register":
            result.registers[key] = widened
        else:
            result.stack[key] = widened
    return result


def _refine_branch_state(
    state: _State, instruction_id: int, edge_kind: str
) -> _State | None:
    """Apply the exact zero/nonzero predicate carried by JE/JNE edges."""

    result = state.copy()
    register = state.zero_register
    if register is None or instruction_id not in {X86_INS_JE, X86_INS_JNE}:
        return result
    value = state.registers.get(register, _BOTTOM)
    if not value.is_finite:
        return result
    branch_taken = edge_kind == "conditional-branch"
    want_zero = branch_taken if instruction_id == X86_INS_JE else not branch_taken
    filtered = frozenset(
        row for row in value.values if (row == 0) == want_zero
    )
    if not filtered:
        return None
    result.registers[register] = _finite(
        filtered,
        "branch-refinement:"
        + ",".join(f"{row:#x}" for row in sorted(filtered)),
    )
    return result


def _call_key(row: CallFact) -> tuple[Any, ...]:
    return (
        row.address,
        row.target,
        row.function_entry,
        tuple(_abstract_key(value) for value in row.arguments),
        _abstract_key(row.return_value),
    )


def _write_key(row: MemoryWriteFact) -> tuple[Any, ...]:
    return (
        row.address,
        row.function_entry,
        row.width,
        _abstract_key(row.base),
        row.offset,
        _abstract_key(row.value),
        row.operation,
    )


def _abstract_key(value: AbstractValue) -> tuple[Any, ...]:
    return (
        value.kind,
        tuple(sorted(value.values)),
        value.affine_base,
        value.affine_stride,
        value.affine_symbol,
        value.affine_terms,
        value.pointer_base,
        value.pointer_offset,
        value.pointer_type,
        value.allocation_site if value.allocation_site is not None else -1,
        value.origin,
    )


def _linear_expression(value: AbstractValue) -> str:
    pieces = [f"{value.affine_base:#x}"]
    pieces.extend(f"{coefficient}*{symbol}" for symbol, coefficient in _terms(value))
    return "+".join(pieces)


def _value_expression(value: AbstractValue) -> str:
    if value.kind in {"argument", "affine"}:
        return _linear_expression(value)
    if value.is_finite:
        return "finite{" + ",".join(f"{row:#x}" for row in sorted(value.values)) + "}"
    if value.kind == "pointer":
        return (
            f"{value.pointer_type}[{value.pointer_base}]"
            f"{value.pointer_offset:+#x}"
        )
    return f"{value.kind}:{value.origin}"


def _affine_alternatives(value: AbstractValue) -> set[str]:
    if value.is_finite:
        return {f"{row:#x}" for row in value.values}
    terms = _terms(value)
    if (
        value.affine_base == 0
        and len(terms) == 1
        and terms[0][1] == 1
        and terms[0][0].startswith("choice{")
        and terms[0][0].endswith("}")
    ):
        return set(terms[0][0][7:-1].split("|"))
    return {_linear_expression(value)}


def _affine_choice(left: AbstractValue, right: AbstractValue) -> AbstractValue:
    alternatives = _affine_alternatives(left) | _affine_alternatives(right)
    if len(alternatives) > 64:
        return _unknown(f"affine-choice-cap:observed={len(alternatives)}")
    symbol = "choice{" + "|".join(sorted(alternatives)) + "}"
    return _linear(0, ((symbol, 1),), f"join:affine-choice:{symbol}")


def _unresolved_key(row: UnresolvedValue) -> tuple[Any, ...]:
    return row.address, row.kind, row.reason, row.origin


def _compute_sccs(
    nodes: set[int], edges: dict[int, set[int]]
) -> list[set[int]]:
    visited: set[int] = set()
    finish_order: list[int] = []
    for root in sorted(nodes):
        if root in visited:
            continue
        stack: list[tuple[int, bool]] = [(root, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                finish_order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for successor in sorted(edges.get(node, ()), reverse=True):
                if successor in nodes and successor not in visited:
                    stack.append((successor, False))

    reverse_edges: dict[int, set[int]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            if source in nodes and target in nodes:
                reverse_edges[target].add(source)
    result: list[set[int]] = []
    visited.clear()
    for root in reversed(finish_order):
        if root in visited:
            continue
        component: set[int] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            stack.extend(
                successor
                for successor in sorted(reverse_edges.get(node, ()), reverse=True)
                if successor not in visited
            )
        result.append(component)
    return result


def _callee_first_sccs(
    sccs: list[set[int]], graph: dict[int, set[int]]
) -> list[set[int]]:
    component_of = {
        node: index for index, component in enumerate(sccs) for node in component
    }
    edges: dict[int, set[int]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            left = component_of[source]
            right = component_of[target]
            if left != right:
                edges[left].add(right)
    callers: dict[int, set[int]] = defaultdict(set)
    remaining_callees = {
        component: len(edges.get(component, ()))
        for component in range(len(sccs))
    }
    for caller, callees in edges.items():
        for callee in callees:
            callers[callee].add(caller)
    ready = [
        component
        for component, count in remaining_callees.items()
        if count == 0
    ]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        component = heapq.heappop(ready)
        order.append(component)
        for caller in sorted(callers.get(component, ())):
            remaining_callees[caller] -= 1
            if remaining_callees[caller] == 0:
                heapq.heappush(ready, caller)
    if len(order) != len(sccs):
        raise ValueError("SCC condensation graph is cyclic")
    return [sccs[index] for index in order]


def analyze_values(
    image: Image,
    cfg: RawCfg,
    control_targets: ControlTargetResult,
    roots: Sequence[int] = (),
    limits: AnalysisLimits | None = None,
) -> AnalysisResult:
    """Compute bounded function summaries and proof-relevant value facts."""

    limits = limits or AnalysisLimits.for_image(image)
    interpreter = _Interpreter(image, cfg, limits)
    functions = set(interpreter.function_entries) | set(roots)
    limits.check("max_functions", len(functions))
    graph = interpreter.call_graph()
    sccs = _callee_first_sccs(_compute_sccs(functions, graph), graph)
    summaries: dict[int, FunctionSummary] = {
        entry: FunctionSummary.empty(entry) for entry in functions
    }
    analyses: dict[int, _FunctionAnalysis] = {}
    summary_updates = 0
    scc_iterations = 0
    max_block_updates = 0
    max_finite_values = 0

    for component in sccs:
        scc_iterations += 1
        limits.check("max_scc_iterations", scc_iterations)
        iteration = 0
        while True:
            iteration += 1
            limits.check("max_summary_iterations", iteration)
            changed = False
            for entry in sorted(component):
                analysis = interpreter.analyze_function(entry, summaries)
                max_block_updates = max(max_block_updates, analysis.block_updates)
                max_finite_values = max(
                    max_finite_values, analysis.finite_value_high_water
                )
                if analysis.summary != summaries[entry]:
                    summaries[entry] = analysis.summary
                    changed = True
                    summary_updates += 1
                    limits.check("max_fixpoint_updates", summary_updates)
                analyses[entry] = analysis
            if not changed:
                break

    unresolved = {
        UnresolvedValue(row.address, "control-target", row.kind, row.detail)
        for row in control_targets.unresolved
    }
    for analysis in analyses.values():
        unresolved.update(analysis.unresolved)
        for allocation in analysis.summary.allocations:
            if allocation.size.is_bottom or allocation.size.is_unknown:
                unresolved.add(
                    UnresolvedValue(
                        allocation.call_address,
                        "allocation-size",
                        "unknown-value-affects-allocation-size",
                        allocation.size.origin,
                    )
                )
    calls = {
        row for analysis in analyses.values() for row in analysis.calls
    }
    writes = {
        row for analysis in analyses.values() for row in analysis.writes
    }
    instruction_hash = hashlib.sha256(
        b"".join(bytes.fromhex(row.bytes_hex) for row in cfg.instructions)
    ).hexdigest()
    return AnalysisResult(
        compiler_sha256=image.sha256,
        cfg_instruction_hash=instruction_hash,
        summaries=tuple(summaries[entry] for entry in sorted(summaries)),
        calls=tuple(sorted(calls, key=_call_key)),
        memory_writes=tuple(sorted(writes, key=_write_key)),
        finite_internal_edges=control_targets.finite_internal_edges,
        terminal_external_edges=control_targets.terminal_external_edges,
        external_escapes=control_targets.external_escapes,
        unresolved=tuple(sorted(unresolved, key=_unresolved_key)),
        proof_ready=not unresolved,
        limits=limits,
        high_water_marks=(
            ("functions", len(functions)),
            ("scc_iterations", scc_iterations),
            ("summary_updates", summary_updates),
            ("block_updates", max_block_updates),
            ("finite_values", max_finite_values),
        ),
    )
