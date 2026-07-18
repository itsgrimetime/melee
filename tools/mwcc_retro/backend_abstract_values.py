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
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, fields, replace
from typing import Any, Iterable, Mapping, Sequence

from capstone import (
    CS_AC_WRITE,
    CS_ARCH_X86,
    CS_GRP_CALL,
    CS_GRP_RET,
    CS_MODE_32,
    Cs,
)
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
    X86_INS_MOVSB,
    X86_INS_MOVSD,
    X86_INS_MOVSW,
    X86_INS_MOVSX,
    X86_INS_MOVZX,
    X86_INS_OR,
    X86_INS_POP,
    X86_INS_PUSH,
    X86_INS_SAL,
    X86_INS_SAR,
    X86_INS_SHL,
    X86_INS_SHR,
    X86_INS_STOSB,
    X86_INS_STOSD,
    X86_INS_STOSW,
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
_STACK_OUTPUT_ARGUMENTS = {
    0x00443390: frozenset({3}),
    0x004C7730: frozenset({2, 3}),
}
_TRACKED_GENERAL_REGISTERS = frozenset(
    {
        X86_REG_EAX,
        X86_REG_EBX,
        X86_REG_ECX,
        X86_REG_EDX,
        X86_REG_ESI,
        X86_REG_EDI,
    }
)
_X87_MEMORY_STORE_MNEMONICS = frozenset(
    {
        "fbstp",
        "fist",
        "fistp",
        "fnstcw",
        "fnstenv",
        "fnstsw",
        "fnsave",
        "fst",
        "fstcw",
        "fstenv",
        "fstp",
        "fstsw",
        "fsave",
    }
)


@dataclass(frozen=True, slots=True)
class ValueDependency:
    """One exact memory/helper dependency carried by an abstract value.

    Dependencies are deliberately structural rather than inferred from rendered
    expression strings.  A formal-argument memory read can be rebound at each
    call boundary; a helper-output dependency binds a caller value to the exact
    callee store that produced it.
    """

    kind: str
    address: int
    width: int
    source_address: int = 0
    pointer_type: str = ""
    pointer_base: int = 0
    pointer_offset: int = 0
    allocation_site: int | None = None
    formal_argument_index: int | None = None
    origin: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"memory-read", "helper-output"}:
            raise ValueError(f"unknown value dependency kind: {self.kind}")
        if self.address < 0 or self.source_address < 0:
            raise ValueError("value dependency addresses must be nonnegative")
        if self.width <= 0:
            raise ValueError("value dependency width must be positive")
        if self.formal_argument_index is not None and self.formal_argument_index < 0:
            raise ValueError("formal argument index must be nonnegative")
        if self.kind == "helper-output" and self.source_address == 0:
            raise ValueError("helper-output dependency requires a source address")

    def bind(
        self,
        arguments: tuple[AbstractValue, ...],
        origin: str,
    ) -> ValueDependency:
        index = self.formal_argument_index
        if index is None:
            return self
        if index >= len(arguments):
            return replace(
                self,
                formal_argument_index=None,
                origin=f"{origin}:missing-argument-{index}",
            )
        actual = arguments[index]
        formal = _single_formal_argument(actual)
        if formal is not None:
            next_index, next_offset = formal
            return replace(
                self,
                pointer_offset=self.pointer_offset + next_offset,
                formal_argument_index=next_index,
                origin=f"{origin}:formal-argument-{index}",
            )
        if actual.kind == "pointer":
            return replace(
                self,
                pointer_type=actual.pointer_type,
                pointer_base=actual.pointer_base,
                pointer_offset=self.pointer_offset + actual.pointer_offset,
                allocation_site=actual.allocation_site,
                formal_argument_index=None,
                origin=f"{origin}:bound-argument-{index}",
            )
        return replace(
            self,
            formal_argument_index=None,
            origin=(
                f"{origin}:unresolved-argument-{index}:"
                f"{actual.kind}:{actual.origin}"
            ),
        )


def _dependency_key(row: ValueDependency) -> tuple[Any, ...]:
    return (
        row.kind,
        row.address,
        row.source_address,
        row.width,
        row.pointer_type,
        row.pointer_base,
        row.pointer_offset,
        row.allocation_site if row.allocation_site is not None else -1,
        row.formal_argument_index if row.formal_argument_index is not None else -1,
        row.origin,
    )


def _merge_dependencies(
    *groups: Iterable[ValueDependency],
) -> tuple[ValueDependency, ...]:
    return tuple(sorted({row for group in groups for row in group}, key=_dependency_key))


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
    dependencies: tuple[ValueDependency, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(row, ValueDependency) for row in self.dependencies
        ):
            raise TypeError("dependencies must be tuple[ValueDependency, ...]")
        canonical = tuple(sorted(self.dependencies, key=_dependency_key))
        if len(set(canonical)) != len(canonical):
            raise ValueError("value dependencies must be unique")
        if self.dependencies != canonical:
            raise ValueError("value dependencies must be canonically ordered")

    def with_dependencies(
        self, dependencies: Iterable[ValueDependency]
    ) -> AbstractValue:
        merged = _merge_dependencies(self.dependencies, dependencies)
        return self if merged == self.dependencies else replace(self, dependencies=merged)

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
                dependencies=self.dependencies,
            )
        if self.kind in {"argument", "affine"}:
            return _linear(
                self.affine_base + delta,
                _terms(self),
                origin,
                self.dependencies,
            )
        if self.is_finite:
            return _finite(
                ((value + delta) & _MASK32 for value in self.values),
                origin,
                self.dependencies,
            )
        if self.kind == "symbolic":
            return _symbolic(
                f"add({_value_expression(self)},{delta})",
                origin,
                self.dependencies,
            )
        return _unknown(f"{origin}:add-to-{self.kind}", self.dependencies)

    def scaled(self, scale: int, origin: str) -> AbstractValue:
        if scale == 1:
            return replace(self, origin=origin)
        if scale == 0:
            return _exact(0, origin, self.dependencies)
        if self.kind in {"argument", "affine"}:
            return _linear(
                self.affine_base * scale,
                ((symbol, coefficient * scale) for symbol, coefficient in _terms(self)),
                origin,
                self.dependencies,
            )
        if self.is_finite:
            return _finite(
                ((value * scale) & _MASK32 for value in self.values),
                origin,
                self.dependencies,
            )
        if self.kind in {"pointer", "symbolic"}:
            return _symbolic(
                f"scale({_value_expression(self)},{scale})",
                origin,
                self.dependencies,
            )
        return _unknown(f"{origin}:scale-{self.kind}", self.dependencies)

    def substitute(
        self, arguments: tuple[AbstractValue, ...], origin: str
    ) -> AbstractValue:
        bound_dependencies = tuple(
            row.bind(arguments, origin) for row in self.dependencies
        )
        if self.kind not in {"argument", "affine"}:
            canonical = _merge_dependencies(bound_dependencies)
            return self if canonical == self.dependencies else replace(
                self, dependencies=canonical
            )
        result = _exact(self.affine_base, origin)
        for symbol, coefficient in _terms(self):
            value: AbstractValue
            if symbol.startswith("arg") and symbol[3:].isdigit():
                index = int(symbol[3:])
                if index >= len(arguments):
                    return _unknown(
                        f"{origin}:missing-argument-{index}",
                        bound_dependencies,
                    )
                value = arguments[index]
            else:
                value = _linear(0, ((symbol, 1),), origin)
            result = _add_values(result, value.scaled(coefficient, origin), origin)
        return result.with_dependencies(bound_dependencies)

    def join(self, other: AbstractValue) -> AbstractValue:
        if self.is_bottom:
            return other
        if other.is_bottom:
            return self
        if self == other:
            return self
        dependencies = _merge_dependencies(self.dependencies, other.dependencies)
        if self.is_unknown:
            return self.with_dependencies(dependencies)
        if other.is_unknown:
            return other.with_dependencies(dependencies)
        if self.is_finite and other.is_finite:
            merged = self.values | other.values
            return _finite(
                merged,
                "join:finite:" + ",".join(f"{row:#x}" for row in sorted(merged)),
                dependencies,
            )
        if (
            self.kind in {"argument", "affine"}
            and other.is_finite
        ) or (
            other.kind in {"argument", "affine"}
            and self.is_finite
        ):
            return _affine_choice(self, other).with_dependencies(dependencies)
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
                dependencies,
            )
        if self.kind in {"argument", "affine"} and other.kind in {
            "argument",
            "affine",
        }:
            return _affine_choice(self, other).with_dependencies(dependencies)
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
                dependencies=dependencies,
            )
        if {self.kind, other.kind} == {"null", "pointer"}:
            pointer = self if self.kind == "pointer" else other
            return _symbolic(
                f"nullable({_value_expression(pointer)})",
                _join_origin(self, other, "nullable-pointer"),
                dependencies,
            )
        if "symbolic" in {self.kind, other.kind}:
            return _symbolic_choice(self, other).with_dependencies(dependencies)
        # Both paths carry concrete provenance even when their numeric/type
        # shapes differ.  The executed program selects one runtime value; this
        # is not missing analyzer knowledge and must not become the absorbing
        # epistemic ``unknown`` element.
        return _symbolic_choice(self, other).with_dependencies(dependencies)


_BOTTOM = AbstractValue()


def _exact(
    value: int,
    origin: str,
    dependencies: Iterable[ValueDependency] = (),
) -> AbstractValue:
    value &= _MASK32
    return AbstractValue(
        kind="null" if value == 0 else "exact",
        values=frozenset({value}),
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _finite(
    values: Iterable[int],
    origin: str,
    dependencies: Iterable[ValueDependency] = (),
) -> AbstractValue:
    frozen = frozenset(value & _MASK32 for value in values)
    if not frozen:
        return _BOTTOM
    return AbstractValue(
        kind="exact" if len(frozen) == 1 else "finite",
        values=frozen,
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _unknown(
    origin: str,
    dependencies: Iterable[ValueDependency] = (),
) -> AbstractValue:
    return AbstractValue(
        kind="unknown",
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _symbolic(
    expression: str,
    origin: str,
    dependencies: Iterable[ValueDependency] = (),
) -> AbstractValue:
    """An origin-bound runtime value whose numeric domain is unconstrained."""

    return AbstractValue(
        kind="symbolic",
        affine_symbol=expression,
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _symbolic_alternatives(value: AbstractValue) -> set[str]:
    expression = _value_expression(value)
    if expression.startswith("choice{") and expression.endswith("}"):
        return set(expression[7:-1].split("|"))
    return {expression}


def _symbolic_choice(
    left: AbstractValue, right: AbstractValue
) -> AbstractValue:
    alternatives = sorted(
        _symbolic_alternatives(left) | _symbolic_alternatives(right)
    )
    rendered = "|".join(alternatives)
    if len(alternatives) > 64 or len(rendered) > 1_024:
        rendered = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    return _symbolic(
        f"choice{{{rendered}}}",
        _join_origin(left, right, "symbolic-choice"),
        _merge_dependencies(left.dependencies, right.dependencies),
    )


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
    dependencies: Iterable[ValueDependency] = (),
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
        return _exact(base, origin, dependencies)
    symbol = canonical[0][0] if len(canonical) == 1 else ""
    stride = canonical[0][1] if len(canonical) == 1 else 0
    return AbstractValue(
        kind="affine",
        affine_base=base,
        affine_stride=stride,
        affine_symbol=symbol,
        affine_terms=canonical,
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _pointer(
    pointer_type: str,
    base: int,
    offset: int,
    origin: str,
    allocation_site: int | None = None,
    dependencies: Iterable[ValueDependency] = (),
) -> AbstractValue:
    return AbstractValue(
        kind="pointer",
        pointer_base=base,
        pointer_offset=offset,
        pointer_type=pointer_type,
        allocation_site=allocation_site,
        origin=origin,
        dependencies=_merge_dependencies(dependencies),
    )


def _single_formal_argument(value: AbstractValue) -> tuple[int, int] | None:
    """Return ``(argument index, byte offset)`` for one exact formal base."""

    if value.kind not in {"argument", "affine"}:
        return None
    terms = _terms(value)
    if len(terms) != 1 or terms[0][1] != 1:
        return None
    symbol = terms[0][0]
    if not symbol.startswith("arg") or not symbol[3:].isdigit():
        return None
    return int(symbol[3:]), value.affine_base


def _memory_dependency(
    pointer: AbstractValue,
    address: int,
    width: int,
) -> ValueDependency:
    formal = _single_formal_argument(pointer)
    if formal is not None:
        index, offset = formal
        return ValueDependency(
            kind="memory-read",
            address=address,
            width=width,
            pointer_offset=offset,
            formal_argument_index=index,
            origin=f"formal-memory-read:{address:#x}:arg{index}{offset:+#x}",
        )
    if pointer.kind == "pointer":
        return ValueDependency(
            kind="memory-read",
            address=address,
            width=width,
            pointer_type=pointer.pointer_type,
            pointer_base=pointer.pointer_base,
            pointer_offset=pointer.pointer_offset,
            allocation_site=pointer.allocation_site,
            origin=f"typed-memory-read:{address:#x}:{pointer.origin}",
        )
    return ValueDependency(
        kind="memory-read",
        address=address,
        width=width,
        origin=f"unresolved-memory-read:{address:#x}:{pointer.kind}:{pointer.origin}",
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
    helper_effects: tuple[MemoryWriteFact, ...] = ()

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
    effect_call_address: int = 0
    effect_is_must: bool = False


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
class ClosureGap:
    """One bounded, provenance-bearing reason a closure is not complete."""

    address: int
    kind: str
    detail: str
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AliasWriteSiteEvidence:
    """One explicit memory-destination operand from the accepted Task 4 CFG."""

    address: int
    operand_index: int
    width: int
    instruction_bytes_hex: str
    instruction_sha256: str
    disposition: str
    facts: tuple[MemoryWriteFact, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AliasWriteClosureCertificate:
    compiler_sha256: str
    cfg_instruction_hash: str
    source_instruction_count: int
    sites: tuple[AliasWriteSiteEvidence, ...]
    gaps: tuple[ClosureGap, ...]
    configured_limits: tuple[tuple[str, int], ...]
    high_water_marks: tuple[tuple[str, int], ...]
    cap_hits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HelperEffectSiteEvidence:
    """One finite call target and its closed Task 5 summary consequences."""

    address: int
    target: int
    function_entries: tuple[int, ...]
    disposition: str
    argument_pointer_types: tuple[str, ...]
    summary_entries: tuple[int, ...]
    allocation_sites: tuple[int, ...]
    typed_write_sites: tuple[int, ...]
    transitive_callees: tuple[int, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleSemanticEvidence:
    kind: str
    address: int
    target: int
    affected_pointer_types: tuple[str, ...]
    affected_arenas: tuple[int, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleEffectClosureCertificate:
    compiler_sha256: str
    cfg_instruction_hash: str
    source_call_instruction_count: int
    sites: tuple[HelperEffectSiteEvidence, ...]
    semantic_evidence: tuple[LifecycleSemanticEvidence, ...]
    covered_write_sites: tuple[int, ...]
    summary_entries: tuple[int, ...]
    gaps: tuple[ClosureGap, ...]
    configured_limits: tuple[tuple[str, int], ...]
    high_water_marks: tuple[tuple[str, int], ...]
    cap_hits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CallReturnWriteEvidence:
    call_address: int
    target: int
    function_entry: int
    write_addresses: tuple[int, ...]
    pcode_argument_indices: tuple[int, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmissionSemanticEvidence:
    """A closed semantic relation needed after an encoder return flow."""

    kind: str
    address: int
    related_addresses: tuple[int, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PseudoOpDispositionEvidence:
    """An exhaustive disposition of the two zero-encoding metadata opcodes."""

    opcode_ids: tuple[int, ...]
    classification: str
    walker_address: int
    disposition_sites: tuple[int, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.opcode_ids != (466, 467):
            raise ValueError("pseudo-op evidence must cover exactly IDs 466 and 467")
        if self.classification not in {
            "removed-before-final-walker",
            "zero-width-skipped-by-final-walker",
        }:
            raise ValueError("unknown pseudo-op disposition classification")
        if self.walker_address <= 0:
            raise ValueError("pseudo-op evidence requires a walker address")
        if (
            not self.disposition_sites
            or tuple(sorted(set(self.disposition_sites))) != self.disposition_sites
        ):
            raise ValueError("pseudo-op disposition sites must be nonempty and canonical")
        if not self.provenance or any(not row for row in self.provenance):
            raise ValueError("pseudo-op evidence requires nonempty provenance")


@dataclass(frozen=True, slots=True)
class FinalEmissionClosureCertificate:
    compiler_sha256: str
    cfg_instruction_hash: str
    return_write_flows: tuple[CallReturnWriteEvidence, ...]
    semantic_evidence: tuple[EmissionSemanticEvidence, ...]
    gaps: tuple[ClosureGap, ...]
    configured_limits: tuple[tuple[str, int], ...]
    high_water_marks: tuple[tuple[str, int], ...]
    cap_hits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FunctionSummary:
    entry: int
    argument_flows: tuple[tuple[int, AbstractValue], ...] = ()
    allocations: tuple[AllocationFact, ...] = ()
    typed_writes: tuple[MemoryWriteFact, ...] = ()
    must_write_sites: tuple[int, ...] = ()
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
    calls: tuple[CallFact, ...] = ()
    memory_writes: tuple[MemoryWriteFact, ...] = ()
    finite_internal_edges: tuple[Any, ...] = ()
    terminal_external_edges: tuple[Any, ...] = ()
    external_escapes: tuple[Any, ...] = ()
    unresolved: tuple[UnresolvedValue, ...] = ()
    proof_ready: bool = False
    limits: AnalysisLimits | None = None
    high_water_marks: tuple[tuple[str, int], ...] = ()
    register_domains: tuple[Any, ...] = ()
    custom_opcode_layouts_proved: bool = False
    variadic_bounds_proved: bool = False
    alias_write_closure: AliasWriteClosureCertificate | None = None
    lifecycle_effect_closure: LifecycleEffectClosureCertificate | None = None
    final_emission_closure: FinalEmissionClosureCertificate | None = None
    pseudo_op_dispositions: tuple[PseudoOpDispositionEvidence, ...] = ()

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

    def _control_site_dominates_returns(
        self,
        entry: int,
        control_address: int,
    ) -> bool:
        """Prove one instruction executes before every reachable return."""

        owned = set(self.function_blocks.get(entry, ()))
        start = self.instruction_block.get(entry, entry)
        control_block = self.instruction_block.get(control_address)
        if start not in owned or control_block not in owned:
            return False
        predecessors: dict[int, set[int]] = {row: set() for row in owned}
        for source in owned:
            for target in self.successors.get(source, ()):
                if target in owned:
                    predecessors[target].add(source)
        dominators: dict[int, set[int]] = {
            row: ({row} if row == start else set(owned)) for row in owned
        }
        for _iteration in range(len(owned) + 1):
            changed = False
            for block in sorted(owned - {start}):
                incoming = predecessors[block]
                if not incoming:
                    updated = {block}
                else:
                    shared = set(owned)
                    for predecessor in incoming:
                        shared &= dominators[predecessor]
                    updated = {block, *shared}
                if updated != dominators[block]:
                    dominators[block] = updated
                    changed = True
            if not changed:
                break
        else:  # pragma: no cover - finite monotone dominators must converge
            raise ValueError(f"dominator fixed point did not converge for {entry:#x}")
        return_blocks = tuple(
            block
            for block in sorted(owned)
            if self._decode(self.blocks[block].instruction_addresses[-1]).group(
                CS_GRP_RET
            )
        )
        if not return_blocks:
            return False
        for block in return_blocks:
            if control_block not in dominators[block]:
                return False
            if control_block == block:
                addresses = self.blocks[block].instruction_addresses
                if addresses.index(control_address) >= len(addresses) - 1:
                    return False
        return True

    def _instantiate_helper_effects(
        self,
        *,
        caller_entry: int,
        call_address: int,
        summary: FunctionSummary,
        arguments: tuple[AbstractValue, ...],
    ) -> tuple[MemoryWriteFact, ...]:
        effects: list[MemoryWriteFact] = []
        for write in summary.typed_writes:
            base = write.base.substitute(
                arguments, f"helper-effect-base:{call_address:#x}"
            )
            value = write.value.substitute(
                arguments, f"helper-effect-value:{call_address:#x}"
            )
            dependency = ValueDependency(
                kind="helper-output",
                address=call_address,
                source_address=write.address,
                width=write.width,
                pointer_type=base.pointer_type,
                pointer_base=base.pointer_base,
                pointer_offset=base.pointer_offset,
                allocation_site=base.allocation_site,
                origin=(
                    f"helper-output:{call_address:#x}->{summary.entry:#x}:"
                    f"store={write.address:#x}"
                ),
            )
            value = value.with_dependencies((dependency,))
            effects.append(
                MemoryWriteFact(
                    address=write.address,
                    function_entry=caller_entry,
                    width=write.width,
                    base=base,
                    offset=(
                        base.pointer_offset
                        if base.kind == "pointer"
                        else write.offset
                    ),
                    value=value,
                    operation=f"helper-effect:{summary.entry:#x}:{write.operation}",
                    effect_call_address=call_address,
                    effect_is_must=write.address in summary.must_write_sites,
                )
            )
        return tuple(sorted(effects, key=_write_key))

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
        updates = 0
        finite_high = 0
        state_updates: dict[int, int] = defaultdict(int)
        discarded_unresolved: set[UnresolvedValue] = set()

        while pending:
            block_start = pending.popleft()
            pending_set.remove(block_start)
            state = incoming[block_start].copy()
            block = self.blocks[block_start]
            for address in block.instruction_addresses:
                decoded = self._decode(address)
                if decoded.group(CS_GRP_CALL):
                    self._eval_call(entry, state, address, summaries)
                    continue
                self._eval_instruction(
                    entry, state, address, discarded_unresolved
                )

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
                        prior, successor_state, successor
                    )
                    joined = _widen_finite_budget(
                        prior,
                        joined,
                        successor,
                        min(4_096, self.limits.max_finite_values - 1),
                    )
                    if state_updates[successor] >= 2:
                        joined = _widen_symbolic_state(
                            prior, joined, successor
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

        # The worklist above necessarily visits transient states.  Publishing
        # facts from those visits makes an early imprecise value permanently
        # poison an otherwise precise final call-site join.  Replay each block
        # once from the accepted fixed-point input and publish only those facts.
        calls: set[CallFact] = set()
        writes: set[MemoryWriteFact] = set()
        unresolved: set[UnresolvedValue] = set()
        returns: list[AbstractValue] = []
        allocations: set[AllocationFact] = set()
        for block_start in sorted(owned):
            if block_start not in incoming:
                continue
            state = incoming[block_start].copy()
            block = self.blocks[block_start]
            for address in block.instruction_addresses:
                decoded = self._decode(address)
                if decoded.group(CS_GRP_CALL):
                    fact, allocation = self._eval_call(
                        entry, state, address, summaries
                    )
                    calls.add(fact)
                    writes.update(fact.helper_effects)
                    if allocation is not None:
                        allocations.add(allocation)
                    continue
                write = self._eval_instruction(
                    entry, state, address, unresolved
                )
                if write is not None:
                    writes.add(write)
                if decoded.group(CS_GRP_RET):
                    returns.append(state.registers.get(X86_REG_EAX, _BOTTOM))

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
                (
                    row
                    for row in writes
                    if row.base.pointer_type != "stack"
                ),
                key=_write_key,
            )
        )
        must_write_sites = tuple(
            sorted(
                {
                    row.address
                    for row in typed_writes
                    if (
                        row.effect_call_address == 0
                        or row.effect_is_must
                    )
                    and self._control_site_dominates_returns(
                        entry,
                        row.effect_call_address or row.address,
                    )
                }
            )
        )
        summary = FunctionSummary(
            entry=entry,
            allocations=tuple(sorted(allocations, key=lambda row: row.call_address)),
            typed_writes=typed_writes,
            must_write_sites=must_write_sites,
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
        arguments = self._recover_direct_push_argument(
            state, address, arguments
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
            summary = summaries[target]
            returned = summary.return_value.substitute(
                arguments, f"call:{address:#x}"
            )
            if returned.is_bottom or returned.is_unknown:
                returned = _symbolic(
                    f"call-return[{address:#x}->{target:#x}]",
                    (
                        f"callee-summary-dynamic-return:{address:#x}:"
                        f"{target:#x}:{returned.origin}"
                    ),
                    returned.dependencies,
                )
            elif returned.kind == "symbolic":
                # A recursive SCC can otherwise grow a fresh expression on
                # every summary iteration (for example ``or(or(...), 1)``).
                # The concrete call site is the stable origin of an
                # unconstrained runtime return value; retain that provenance
                # without embedding the callee's evolving expression tree.
                returned = _symbolic(
                    f"call-return[{address:#x}->{target:#x}]",
                    f"callee-summary-symbolic-return:{address:#x}:{target:#x}",
                    returned.dependencies,
                )
        else:
            returned = _symbolic(
                f"call-return[{address:#x}->{target:#x}]",
                f"unmodelled-call-return:{address:#x}:{target:#x}",
            )

        helper_effects = (
            self._instantiate_helper_effects(
                caller_entry=entry,
                call_address=address,
                summary=summaries[target],
                arguments=arguments,
            )
            if target in summaries
            else ()
        )
        stack_effects: dict[int, list[MemoryWriteFact]] = defaultdict(list)
        for effect in helper_effects:
            if (
                effect.base.kind == "pointer"
                and effect.base.pointer_type == "stack"
            ):
                stack_effects[effect.base.pointer_offset].append(effect)
        for offset, effects in stack_effects.items():
            has_must_effect = any(row.effect_is_must for row in effects)
            prior = _BOTTOM if has_must_effect else state.stack.get(offset, _BOTTOM)
            if prior.is_bottom and not has_must_effect:
                prior = _unknown(
                    f"helper-may-preserve-unmaterialized-stack:{address:#x}:"
                    f"offset={offset}"
                )
            for effect in effects:
                prior = prior.join(effect.value)
            state.stack[offset] = prior

        for index in _STACK_OUTPUT_ARGUMENTS.get(target, ()):
            if index >= len(arguments):
                continue
            pointer = arguments[index]
            if pointer.kind != "pointer" or pointer.pointer_type != "stack":
                continue
            state.stack[pointer.pointer_offset] = _symbolic(
                (
                    f"call-output[{address:#x}:arg{index}:"
                    f"stack={pointer.pointer_offset}]"
                ),
                f"reviewed-stack-output:{address:#x}:{target:#x}:arg{index}",
            )

        for register in (X86_REG_EAX, X86_REG_ECX, X86_REG_EDX):
            state.registers.pop(register, None)
        state.registers[X86_REG_EAX] = returned
        state.zero_register = None
        return (
            CallFact(
                address,
                target,
                entry,
                arguments,
                returned,
                helper_effects,
            ),
            allocation,
        )

    def _recover_direct_push_argument(
        self,
        state: _State,
        address: int,
        arguments: tuple[AbstractValue, ...],
    ) -> tuple[AbstractValue, ...]:
        """Recover arg0 from its local PUSH when ESP provenance was joined away."""

        if not arguments or not (
            arguments[0].is_bottom or arguments[0].is_unknown
        ):
            return arguments
        block_start = self.instruction_block.get(address)
        block = self.blocks.get(block_start) if block_start is not None else None
        if block is None:
            return arguments
        try:
            index = block.instruction_addresses.index(address)
        except ValueError:
            return arguments
        for prior_address in reversed(block.instruction_addresses[max(0, index - 32):index]):
            prior = self._decode(prior_address)
            if prior.group(CS_GRP_CALL) or prior.group(CS_GRP_RET):
                break
            if prior.id == X86_INS_PUSH and prior.operands:
                recovered = self._read_operand(
                    state, prior.operands[0], prior_address
                )
                if recovered.is_bottom or recovered.is_unknown:
                    return arguments
                mutable = list(arguments)
                mutable[0] = recovered
                return tuple(mutable)
            if prior.id == X86_INS_POP or (
                prior.operands
                and prior.operands[0].type == X86_OP_REG
                and _canonical_register(prior, prior.operands[0].reg)
                == X86_REG_ESP
            ):
                break
        return arguments

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
            _read_registers, written_registers = insn.regs_access()
            for register in written_registers:
                canonical = _canonical_register(insn, register)
                if canonical not in _TRACKED_GENERAL_REGISTERS:
                    continue
                origin = (
                    f"implicit-register-result:{address:#x}:{insn.mnemonic}"
                )
                state.registers[canonical] = _symbolic(
                    (
                        f"instruction-result[{address:#x}:"
                        f"{insn.mnemonic}:{canonical}]"
                    ),
                    origin,
                )
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

        if insn.id in {X86_INS_STOSB, X86_INS_STOSW, X86_INS_STOSD} and len(
            operands
        ) == 2:
            count = state.registers.get(X86_REG_ECX, _BOTTOM)
            if not insn.mnemonic.startswith("rep "):
                count = _exact(1, f"single-{insn.mnemonic}:{address:#x}")
            value = self._read_operand(state, operands[1], address)
            write = self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=f"{insn.mnemonic} count={_value_expression(count)}",
            )
            byte_count = count.scaled(
                operands[0].size, f"stos-byte-count:{address:#x}"
            )
            state.registers[X86_REG_EDI] = _add_values(
                state.registers.get(X86_REG_EDI, _BOTTOM),
                byte_count,
                f"stos-advance:{address:#x}",
            )
            if insn.mnemonic.startswith("rep "):
                state.registers[X86_REG_ECX] = _exact(
                    0, f"rep-stos-count-consumed:{address:#x}"
                )
            return write

        if (
            insn.id in {X86_INS_MOVSB, X86_INS_MOVSW, X86_INS_MOVSD}
            and len(operands) == 2
            and all(operand.type == X86_OP_MEM for operand in operands)
        ):
            repeated = insn.mnemonic.startswith("rep ")
            count = (
                state.registers.get(X86_REG_ECX, _BOTTOM)
                if repeated
                else _exact(1, f"single-movsd:{address:#x}")
            )
            value = self._read_operand(state, operands[1], address)
            operation = f"{insn.mnemonic} count={_value_expression(count)}"
            write = self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=operation,
            )
            byte_count = count.scaled(
                operands[0].size, f"movs-byte-count:{address:#x}"
            )
            for register in (X86_REG_ESI, X86_REG_EDI):
                state.registers[register] = _add_values(
                    state.registers.get(register, _BOTTOM),
                    byte_count,
                    f"movsd-advance:{address:#x}:{register}",
                )
            if repeated:
                state.registers[X86_REG_ECX] = _exact(
                    0, f"rep-movsd-count-consumed:{address:#x}"
                )
            return write
        if insn.id == X86_INS_POP:
            value = _unknown(f"pop-unknown-stack:{address:#x}")
            if state.esp_offset is not None:
                value = state.stack.get(state.esp_offset, _BOTTOM)
                state.esp_offset += 4
            return self._write_operand(
                state, operands[0], value, address, entry=entry, operation="pop"
            )

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

        if (
            insn.mnemonic.startswith("set")
            and len(operands) == 1
            and operands[0].type == X86_OP_MEM
        ):
            value = _symbolic(
                f"condition-code[{address:#x}:{insn.mnemonic}]",
                f"setcc-result:{address:#x}:{insn.mnemonic}",
            )
            return self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )

        if insn.mnemonic in {"neg", "not"} and len(operands) == 1:
            old = self._read_operand(state, operands[0], address)
            if old.is_finite:
                mask = (1 << (operands[0].size * 8)) - 1
                value = _finite(
                    (
                        (-row if insn.mnemonic == "neg" else ~row) & mask
                        for row in old.values
                    ),
                    f"{insn.mnemonic}:{address:#x}",
                    old.dependencies,
                )
            elif old.is_bottom or old.is_unknown:
                value = _unknown(
                    f"{insn.mnemonic}-unknown-input:{address:#x}:{old.origin}",
                    old.dependencies,
                )
            else:
                value = _symbolic(
                    f"{insn.mnemonic}({_value_expression(old)})",
                    f"{insn.mnemonic}:{address:#x}",
                    old.dependencies,
                )
            return self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )

        if insn.mnemonic in {"adc", "sbb"} and len(operands) == 2:
            left = self._read_operand(state, operands[0], address)
            right = self._read_operand(state, operands[1], address)
            value = _symbolic(
                (
                    f"{insn.mnemonic}({_value_expression(left)},"
                    f"{_value_expression(right)},carry)"
                ),
                f"{insn.mnemonic}-with-carry:{address:#x}",
                _merge_dependencies(left.dependencies, right.dependencies),
            )
            state.zero_register = None
            return self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )

        if (
            insn.mnemonic in _X87_MEMORY_STORE_MNEMONICS
            and len(operands) == 1
            and operands[0].type == X86_OP_MEM
        ):
            value = _symbolic(
                f"x87-store[{address:#x}:{insn.mnemonic}]",
                f"x87-store-result:{address:#x}:{insn.mnemonic}",
            )
            return self._write_operand(
                state,
                operands[0],
                value,
                address,
                entry=entry,
                operation=insn.mnemonic,
            )

        if insn.id in {
            X86_INS_ADD,
            X86_INS_SUB,
            X86_INS_IMUL,
            X86_INS_AND,
            X86_INS_OR,
            X86_INS_XOR,
            X86_INS_SHL,
            X86_INS_SAL,
            X86_INS_SHR,
            X86_INS_SAR,
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
        _read_registers, written_registers = insn.regs_access()
        for register in written_registers:
            canonical = _canonical_register(insn, register)
            if canonical not in _TRACKED_GENERAL_REGISTERS:
                continue
            origin = f"unsupported-register-result:{address:#x}:{insn.mnemonic}"
            state.registers[canonical] = _symbolic(
                f"instruction-result[{address:#x}:{insn.mnemonic}:{canonical}]",
                origin,
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
                value = state.stack.get(pointer.pointer_offset, _BOTTOM)
                if value.is_bottom:
                    return _symbolic(
                        (
                            f"stack-memory[{pointer.pointer_offset}:"
                            f"u{operand.size * 8}]"
                        ),
                        (
                            f"unmaterialized-stack-read:{address:#x}:"
                            f"{pointer.pointer_offset}"
                        ),
                    )
                return value
            if pointer.pointer_type == "image":
                absolute = pointer.pointer_base + pointer.pointer_offset
                dependency = _memory_dependency(pointer, address, operand.size)
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
                        (dependency,),
                    )
                try:
                    payload = self.image.read(absolute, operand.size)
                except ValueError:
                    return _unknown(
                        f"unmapped-image-read:{address:#x}:{absolute:#x}",
                        (dependency,),
                    )
                return _exact(
                    int.from_bytes(payload, "little"),
                    f"image-read:{address:#x}:{absolute:#x}",
                    (dependency,),
                )
            if pointer.kind in {"argument", "affine", "symbolic"}:
                expression = _value_expression(pointer)
                read = f"memory[{expression}]:u{operand.size * 8}"
                dependency = _memory_dependency(pointer, address, operand.size)
                if pointer.kind == "symbolic":
                    return _symbolic(
                        read,
                        f"symbolic-read:{address:#x}",
                        (dependency,),
                    )
                return _linear(
                    0,
                    ((read, 1),),
                    f"symbolic-read:{address:#x}",
                    (dependency,),
                )
            if pointer.kind == "pointer":
                dependency = _memory_dependency(pointer, address, operand.size)
                return _linear(
                    0,
                    ((
                        f"{pointer.pointer_type}[{pointer.pointer_base}]"
                        f"{pointer.pointer_offset:+#x}:u{operand.size * 8}",
                        1,
                    ),),
                    f"typed-read:{address:#x}",
                    (dependency,),
                )
            if pointer.is_unknown:
                dependency = _memory_dependency(pointer, address, operand.size)
                return _symbolic(
                    (
                        f"unknown-address[{address:#x}:"
                        f"{pointer.origin}]:u{operand.size * 8}"
                    ),
                    f"unknown-address-read:{address:#x}:{pointer.origin}",
                    (dependency,),
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
            old = state.registers.get(register, _BOTTOM)
            register_name = insn.reg_name(operand.reg)
            if register_name in {"ah", "bh", "ch", "dh"}:
                state.registers[register] = _symbolic(
                    (
                        f"replace-high8({_value_expression(old)},"
                        f"{_value_expression(value)})"
                    ),
                    f"reg-write:{address:#x}",
                    _merge_dependencies(old.dependencies, value.dependencies),
                )
            else:
                state.registers[register] = _write_width(
                    old,
                    value,
                    operand.size,
                    f"reg-write:{address:#x}",
                )
            return None
        if operand.type == X86_OP_MEM:
            pointer = self._effective_address(state, operand, address)
            if pointer.pointer_type == "stack":
                stored = _truncate_value(
                    value, operand.size, f"stack-write:{address:#x}"
                )
                state.stack[pointer.pointer_offset] = stored
                return MemoryWriteFact(
                    address=address,
                    function_entry=entry or 0,
                    width=operand.size,
                    base=pointer,
                    offset=pointer.pointer_offset,
                    value=stored,
                    operation=operation,
                )
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
    if size >= 4:
        return value
    if value.is_finite:
        return _finite(
            (row & ((1 << (size * 8)) - 1) for row in value.values),
            origin,
            value.dependencies,
        )
    if value.kind in {"pointer", "argument", "affine", "symbolic"}:
        return _symbolic(
            f"truncate{size * 8}({_value_expression(value)})",
            origin,
            value.dependencies,
        )
    return value


def _extend_value(
    value: AbstractValue, size: int, *, signed: bool, origin: str
) -> AbstractValue:
    if value.kind in {"pointer", "argument", "affine", "symbolic"}:
        operation = "sign-extend" if signed else "zero-extend"
        return _symbolic(
            f"{operation}{size * 8}({_value_expression(value)})",
            origin,
            value.dependencies,
        )
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
    return _finite(rows, origin, value.dependencies)


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
            _merge_dependencies(old.dependencies, new.dependencies),
        )
    if old.is_bottom and new.is_bottom:
        return _BOTTOM
    if old.is_unknown or new.is_unknown:
        return _unknown(
            f"{origin}:partial-register-write",
            _merge_dependencies(old.dependencies, new.dependencies),
        )
    return _symbolic(
        (
            f"replace-low{size * 8}({_value_expression(old)},"
            f"{_value_expression(new)})"
        ),
        origin,
        _merge_dependencies(old.dependencies, new.dependencies),
    )


def _add_values(
    left: AbstractValue, right: AbstractValue, origin: str
) -> AbstractValue:
    if right.is_exact:
        return left.with_offset(
            _signed32(right.exact_value or 0), origin
        ).with_dependencies(right.dependencies)
    if left.is_exact:
        return right.with_offset(
            _signed32(left.exact_value or 0), origin
        ).with_dependencies(left.dependencies)
    if left.kind in {"argument", "affine"} and right.is_finite:
        domain = ",".join(f"{row:#x}" for row in sorted(right.values))
        return _linear(
            left.affine_base,
            (*_terms(left), (f"finite{{{domain}}}", 1)),
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if right.kind in {"argument", "affine"} and left.is_finite:
        domain = ",".join(f"{row:#x}" for row in sorted(left.values))
        return _linear(
            right.affine_base,
            (*_terms(right), (f"finite{{{domain}}}", 1)),
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if left.kind in {"argument", "affine"} and right.kind in {
        "argument",
        "affine",
    }:
        return _linear(
            left.affine_base + right.affine_base,
            (*_terms(left), *_terms(right)),
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if left.is_finite and right.is_finite:
        return _finite(
            (a + b for a in left.values for b in right.values),
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if not any(
        value.is_bottom or value.is_unknown for value in (left, right)
    ):
        return _symbolic(
            f"add({_value_expression(left)},{_value_expression(right)})",
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    return _unknown(
        f"{origin}:non-affine-add",
        _merge_dependencies(left.dependencies, right.dependencies),
    )


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
            return left.with_offset(
                -_signed32(right.exact_value or 0), origin
            ).with_dependencies(right.dependencies)
        if right.kind in {"argument", "affine"}:
            return _add_values(left, right.scaled(-1, origin), origin)
    if instruction_id == X86_INS_IMUL and right.is_exact:
        return left.scaled(
            _signed32(right.exact_value or 0), origin
        ).with_dependencies(right.dependencies)
    if (
        instruction_id in {X86_INS_SHL, X86_INS_SAL}
        and right.is_exact
        and left.kind in {"argument", "affine"}
    ):
        return left.scaled(
            1 << ((right.exact_value or 0) & 0x1F), origin
        ).with_dependencies(right.dependencies)
    if (
        instruction_id == X86_INS_AND
        and right.is_exact
        and left.kind in {"argument", "affine"}
        and (right.exact_value or 0).bit_count() == 1
    ):
        return _finite(
            (0, right.exact_value or 0),
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if instruction_id == X86_INS_XOR and left == right:
        return _exact(
            0,
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    if left.is_finite and right.is_finite:
        operator = {
            X86_INS_AND: lambda a, b: a & b,
            X86_INS_OR: lambda a, b: a | b,
            X86_INS_XOR: lambda a, b: a ^ b,
            X86_INS_SHL: lambda a, b: a << b,
            X86_INS_SAL: lambda a, b: a << b,
            X86_INS_SHR: lambda a, b: a >> b,
            X86_INS_SAR: lambda a, b: _signed32(a) >> b,
        }.get(instruction_id)
        if operator is not None:
            return _finite(
                (operator(a, b) for a in left.values for b in right.values),
                origin,
                _merge_dependencies(left.dependencies, right.dependencies),
            )
    if not any(
        value.is_bottom or value.is_unknown for value in (left, right)
    ):
        operation = {
            X86_INS_SUB: "sub",
            X86_INS_IMUL: "imul",
            X86_INS_AND: "and",
            X86_INS_OR: "or",
            X86_INS_XOR: "xor",
            X86_INS_SHL: "shl",
            X86_INS_SAL: "sal",
            X86_INS_SHR: "shr",
            X86_INS_SAR: "sar",
        }.get(instruction_id, f"instruction-{instruction_id}")
        return _symbolic(
            f"{operation}({_value_expression(left)},{_value_expression(right)})",
            origin,
            _merge_dependencies(left.dependencies, right.dependencies),
        )
    return _unknown(
        f"{origin}:unsupported-value-operation",
        _merge_dependencies(left.dependencies, right.dependencies),
    )


def _signed32(value: int) -> int:
    value &= _MASK32
    return value - (1 << 32) if value & (1 << 31) else value


def _join_states(
    left: _State, right: _State, join_site: int
) -> tuple[_State, int]:
    registers: dict[int, AbstractValue] = {}
    for register in set(left.registers) | set(right.registers):
        before = left.registers.get(register, _BOTTOM)
        incoming = right.registers.get(register, _BOTTOM)
        joined = before.join(incoming)
        if joined.kind == "symbolic" and before != incoming:
            joined = _symbolic(
                f"phi[{join_site:#x}:register={register}]",
                f"symbolic-join:{join_site:#x}:register={register}",
                _merge_dependencies(before.dependencies, incoming.dependencies),
            )
        registers[register] = joined
    stack: dict[int, AbstractValue] = {}
    for offset in set(left.stack) | set(right.stack):
        before = left.stack.get(offset, _BOTTOM)
        incoming = right.stack.get(offset, _BOTTOM)
        joined = before.join(incoming)
        if joined.kind == "symbolic" and before != incoming:
            joined = _symbolic(
                f"phi[{join_site:#x}:stack={offset}]",
                f"symbolic-join:{join_site:#x}:stack={offset}",
                _merge_dependencies(before.dependencies, incoming.dependencies),
            )
        stack[offset] = joined
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
        if value != before and (
            value.is_finite
            or value.kind in {"affine", "argument", "symbolic"}
        ):
            origin = f"loop-widen:block={block:#x}:register={register}"
            result.registers[register] = _symbolic(
                f"loop-phi[{block:#x}:register={register}]",
                origin,
                _merge_dependencies(before.dependencies, value.dependencies),
            )
    for offset, value in tuple(result.stack.items()):
        before = prior.stack.get(offset, _BOTTOM)
        if value != before and (
            value.is_finite
            or value.kind in {"affine", "argument", "symbolic"}
        ):
            origin = f"loop-widen:block={block:#x}:stack={offset}"
            result.stack[offset] = _symbolic(
                f"loop-phi[{block:#x}:stack={offset}]",
                origin,
                _merge_dependencies(before.dependencies, value.dependencies),
            )
    return result


def _widen_symbolic_state(
    prior: _State, joined: _State, block: int
) -> _State:
    """Collapse a changing runtime expression to a stable loop-phi identity."""

    result = joined.copy()
    for register, value in tuple(result.registers.items()):
        before = prior.registers.get(register, _BOTTOM)
        if value.kind == "symbolic" and value != before:
            origin = f"symbolic-widen:block={block:#x}:register={register}"
            result.registers[register] = _symbolic(
                f"loop-phi[{block:#x}:register={register}]",
                origin,
                _merge_dependencies(before.dependencies, value.dependencies),
            )
    for offset, value in tuple(result.stack.items()):
        before = prior.stack.get(offset, _BOTTOM)
        if value.kind == "symbolic" and value != before:
            origin = f"symbolic-widen:block={block:#x}:stack={offset}"
            result.stack[offset] = _symbolic(
                f"loop-phi[{block:#x}:stack={offset}]",
                origin,
                _merge_dependencies(before.dependencies, value.dependencies),
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
        origin = (
            f"finite-widen:block={block:#x}:{location}={key}:values={size}"
        )
        widened = _symbolic(
            f"finite-domain[{block:#x}:{location}={key}]",
            origin,
            (
                result.registers[key].dependencies
                if location == "register"
                else result.stack[key].dependencies
            ),
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
        tuple(_write_key(value) for value in row.helper_effects),
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
        row.effect_call_address,
        row.effect_is_must,
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
        tuple(_dependency_key(row) for row in value.dependencies),
    )


def _abstract_semantic_key(value: AbstractValue) -> tuple[Any, ...]:
    """Identity used to follow a value across stores that replace its origin."""

    key = _abstract_key(value)
    return (*key[:10], key[11])


def _linear_expression(value: AbstractValue) -> str:
    pieces = [f"{value.affine_base:#x}"]
    pieces.extend(f"{coefficient}*{symbol}" for symbol, coefficient in _terms(value))
    return "+".join(pieces)


def _value_expression(value: AbstractValue) -> str:
    if value.kind in {"argument", "affine"}:
        return _linear_expression(value)
    if value.kind == "symbolic":
        return value.affine_symbol or value.origin
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


def _configured_limit_items(limits: AnalysisLimits) -> tuple[tuple[str, int], ...]:
    return tuple(
        (row.name, int(getattr(limits, row.name)))
        for row in fields(limits)
        if isinstance(getattr(limits, row.name), int)
    )


def _decode_cfg_instruction(row: Any, decoder: Cs | None = None) -> Any:
    decoder = decoder or Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    payload = bytes.fromhex(row.bytes_hex)
    instruction = next(decoder.disasm(payload, row.address), None)
    if instruction is None or instruction.size != row.size:
        raise ValueError(
            f"cannot re-decode accepted instruction at {row.address:#x}"
        )
    return instruction


def _memory_write_obligations(
    cfg: RawCfg,
) -> tuple[tuple[int, int, int, str, str], ...]:
    """Enumerate every explicit memory destination in accepted CFG bytes."""

    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    obligations: list[tuple[int, int, int, str, str]] = []
    for row in sorted(cfg.instructions, key=lambda item: item.address):
        instruction = _decode_cfg_instruction(row, decoder)
        for index, operand in enumerate(instruction.operands):
            if operand.type != X86_OP_MEM or not (
                operand.access & CS_AC_WRITE
                or (
                    index == 0
                    and instruction.mnemonic in _X87_MEMORY_STORE_MNEMONICS
                )
            ):
                continue
            obligations.append(
                (
                    row.address,
                    index,
                    operand.size,
                    row.bytes_hex,
                    hashlib.sha256(bytes.fromhex(row.bytes_hex)).hexdigest(),
                )
            )
    return tuple(obligations)


def _alias_write_disposition(
    facts: tuple[MemoryWriteFact, ...],
) -> tuple[str, str | None]:
    if not facts:
        return "unmodelled-store", "unmodelled-memory-write"
    types = {row.base.pointer_type for row in facts}
    kinds = {row.base.kind for row in facts}
    if types == {"stack"}:
        return "proved-stack-disjoint", None
    if kinds <= {"pointer"} and types <= {
        "pcode",
        "objobject",
        "arena-allocation",
    }:
        return "modelled-lifecycle-storage", None
    if any(
        row.base.is_bottom
        or row.base.is_unknown
        or row.base.kind in {"argument", "affine", "symbolic"}
        or not row.base.pointer_type
        for row in facts
    ):
        return "possibly-aliasing-unknown-base", "possibly-aliasing-memory-write"
    if types == {"image"}:
        return "proved-image-storage-disjoint", None
    if kinds <= {"pointer"} and all(types):
        if types & {"pcode", "objobject", "arena-allocation"}:
            return "exhaustively-typed-lifecycle-or-disjoint-storage", None
        return "proved-distinct-typed-storage", None
    return "unclassified-pointer-store", "unclassified-pointer-memory-write"


def _expected_incoming_calls(
    cfg: RawCfg,
    finite_internal_edges: Sequence[Any],
) -> dict[int, set[int]]:
    incoming: dict[int, set[int]] = defaultdict(set)
    for row in cfg.direct_calls:
        incoming[row.target].add(row.address)
    for row in finite_internal_edges:
        if str(getattr(row, "flow_kind", "")).startswith("indirect-call"):
            incoming[int(getattr(row, "target"))].add(
                int(getattr(row, "source"))
            )
    return incoming


def _resolve_formal_write_fact(
    fact: MemoryWriteFact,
    *,
    calls_by_target: Mapping[int, tuple[CallFact, ...]],
    expected_incoming: Mapping[int, set[int]],
    limits: AnalysisLimits,
    trail: tuple[tuple[int, int], ...] = (),
) -> tuple[MemoryWriteFact, ...]:
    formal = _single_formal_argument(fact.base)
    if formal is None:
        return (fact,)
    index, _offset = formal
    identity = (fact.function_entry, index)
    if identity in trail:
        return (
            replace(
                fact,
                base=_unknown(
                    "formal-write-cycle:"
                    + "->".join(
                        f"{entry:#x}:arg{argument}"
                        for entry, argument in (*trail, identity)
                    )
                ),
                operation=f"{fact.operation}:formal-cycle",
            ),
        )
    expected = expected_incoming.get(fact.function_entry, set())
    paths = tuple(
        row
        for row in calls_by_target.get(fact.function_entry, ())
        if row.address in expected
    )
    covered = {row.address for row in paths}
    if not expected or covered != expected:
        detail = (
            "no-incoming-call"
            if not expected
            else "missing=" + ",".join(
                f"{row:#x}" for row in sorted(expected - covered)
            )
        )
        return (
            replace(
                fact,
                base=_unknown(
                    f"formal-write-incoming-open:{fact.function_entry:#x}:"
                    f"arg{index}:{detail}"
                ),
                operation=f"{fact.operation}:formal-incoming-open",
            ),
        )
    resolved: list[MemoryWriteFact] = []
    for path in sorted(paths, key=_call_key):
        base = fact.base.substitute(
            path.arguments,
            f"formal-write:{path.address:#x}->{fact.function_entry:#x}",
        )
        value = fact.value.substitute(
            path.arguments,
            f"formal-write-value:{path.address:#x}->{fact.function_entry:#x}",
        )
        rebound = replace(
            fact,
            function_entry=path.function_entry,
            base=base,
            offset=(base.pointer_offset if base.kind == "pointer" else fact.offset),
            value=value,
            operation=f"{fact.operation}:formal-path={path.address:#x}",
        )
        resolved.extend(
            _resolve_formal_write_fact(
                rebound,
                calls_by_target=calls_by_target,
                expected_incoming=expected_incoming,
                limits=limits,
                trail=(*trail, identity),
            )
        )
        limits.check("max_finite_values", len(resolved))
    return tuple(sorted(set(resolved), key=_write_key))


def derive_alias_write_closure(
    cfg: RawCfg,
    *,
    compiler_sha256: str,
    cfg_instruction_hash: str,
    memory_writes: Sequence[MemoryWriteFact],
    calls: Sequence[CallFact] = (),
    finite_internal_edges: Sequence[Any] = (),
    limits: AnalysisLimits,
) -> AliasWriteClosureCertificate:
    """Derive a complete memory-destination partition from accepted CFG bytes."""

    calls_by_target: dict[int, tuple[CallFact, ...]] = {
        target: tuple(sorted(rows, key=_call_key))
        for target, rows in (
            (
                target,
                tuple(row for row in calls if row.target == target),
            )
            for target in sorted({row.target for row in calls if row.target})
        )
    }
    expected_incoming = _expected_incoming_calls(cfg, finite_internal_edges)
    resolved_writes = tuple(
        row
        for write in sorted(memory_writes, key=_write_key)
        for row in _resolve_formal_write_fact(
            write,
            calls_by_target=calls_by_target,
            expected_incoming=expected_incoming,
            limits=limits,
        )
    )
    facts_by_address: dict[int, list[MemoryWriteFact]] = defaultdict(list)
    for fact in resolved_writes:
        facts_by_address[fact.address].append(fact)
    sites: list[AliasWriteSiteEvidence] = []
    gaps: list[ClosureGap] = []
    obligations = _memory_write_obligations(cfg)
    obligation_counts: dict[int, int] = defaultdict(int)
    for address, _operand_index, _width, _bytes_hex, _digest in obligations:
        obligation_counts[address] += 1
    for address, operand_index, width, bytes_hex, digest in obligations:
        facts = tuple(sorted(facts_by_address.get(address, ()), key=_write_key))
        disposition, gap_kind = _alias_write_disposition(facts)
        if obligation_counts[address] != 1:
            disposition = "multiple-memory-destinations-unbound"
            gap_kind = "multiple-memory-destinations-unbound"
        provenance = (
            f"accepted-cfg-instruction:{address:#x}:{bytes_hex}",
            f"memory-destination-operand:{operand_index}:width={width}",
            *(f"write-fact:{row.function_entry:#x}:{row.operation}" for row in facts),
        )
        sites.append(
            AliasWriteSiteEvidence(
                address,
                operand_index,
                width,
                bytes_hex,
                digest,
                disposition,
                facts,
                provenance,
            )
        )
        if gap_kind is not None:
            gaps.append(
                ClosureGap(
                    address,
                    gap_kind,
                    f"operand={operand_index};width={width};disposition={disposition}",
                    provenance,
                )
            )
    obligation_addresses = {row[0] for row in obligations}
    for address in sorted(set(facts_by_address) - obligation_addresses):
        facts = tuple(sorted(facts_by_address[address], key=_write_key))
        gaps.append(
            ClosureGap(
                address,
                "write-fact-without-cfg-memory-destination",
                f"facts={len(facts)}",
                tuple(
                    f"write-fact:{row.function_entry:#x}:{row.operation}"
                    for row in facts
                ),
            )
        )
    fact_key_counts = Counter(_write_key(row) for row in resolved_writes)
    for key in sorted(row for row, count in fact_key_counts.items() if count != 1):
        gaps.append(
            ClosureGap(
                int(key[0]),
                "duplicate-memory-write-fact",
                repr(key),
            )
        )
    sites_tuple = tuple(sites)
    unresolved_count = len(gaps)
    return AliasWriteClosureCertificate(
        compiler_sha256,
        cfg_instruction_hash,
        len(cfg.instructions),
        sites_tuple,
        tuple(sorted(gaps, key=lambda row: (row.address, row.kind, row.detail))),
        _configured_limit_items(limits),
        (
            ("memory_write_facts", len(resolved_writes)),
            ("memory_write_operands", len(sites_tuple)),
            ("unresolved_write_operands", unresolved_count),
        ),
    )


def _call_target_obligations(
    cfg: RawCfg,
    calls: Sequence[CallFact],
    finite_internal_edges: Sequence[Any],
    terminal_external_edges: Sequence[Any],
) -> tuple[tuple[int, int], ...]:
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    call_addresses = {
        row.address
        for row in cfg.instructions
        if _decode_cfg_instruction(row, decoder).group(CS_GRP_CALL)
    }
    targets: dict[int, set[int]] = defaultdict(set)
    targets.update(
        {
            row.address: {row.target}
            for row in cfg.direct_calls
            if row.address in call_addresses
        }
    )
    for row in finite_internal_edges:
        source = getattr(row, "source", -1)
        flow_kind = getattr(row, "flow_kind", "")
        if source in call_addresses and (
            flow_kind == "direct-call" or flow_kind.startswith("indirect-call")
        ):
            targets[source].add(int(getattr(row, "target")))
    for row in terminal_external_edges:
        source = getattr(row, "source", -1)
        if source not in call_addresses:
            continue
        target = getattr(row, "target", None)
        if target is None:
            target = getattr(row, "iat_va", 0)
        targets[source].add(int(target))
    for row in calls:
        if row.address in call_addresses and row.target:
            targets[row.address].add(row.target)
    return tuple(
        (address, target)
        for address in sorted(call_addresses)
        for target in sorted(targets.get(address, {0}))
    )


def _transitive_summary_effects(
    entry: int, summaries: dict[int, FunctionSummary]
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    pending = [entry]
    visited: set[int] = set()
    allocations: set[int] = set()
    writes: set[int] = set()
    callees: set[int] = set()
    while pending:
        current = pending.pop()
        if current in visited or current not in summaries:
            continue
        visited.add(current)
        summary = summaries[current]
        allocations.update(row.call_address for row in summary.allocations)
        writes.update(row.address for row in summary.typed_writes)
        for callee in summary.callees:
            callees.add(callee)
            if callee in summaries and callee not in visited:
                pending.append(callee)
    return (
        tuple(sorted(visited)),
        tuple(sorted(allocations)),
        tuple(sorted(writes)),
        tuple(sorted(callees)),
    )


def derive_lifecycle_effect_closure(
    cfg: RawCfg,
    *,
    compiler_sha256: str,
    cfg_instruction_hash: str,
    summaries: Sequence[FunctionSummary],
    calls: Sequence[CallFact],
    memory_writes: Sequence[MemoryWriteFact],
    finite_internal_edges: Sequence[Any],
    terminal_external_edges: Sequence[Any],
    limits: AnalysisLimits,
) -> LifecycleEffectClosureCertificate:
    """Bind every call target to its transitive modeled helper effects."""

    summary_map = {row.entry: row for row in summaries}
    calls_by_target: dict[int, tuple[CallFact, ...]] = {
        target: tuple(sorted(rows, key=_call_key))
        for target, rows in (
            (target, tuple(row for row in calls if row.target == target))
            for target in sorted({row.target for row in calls if row.target})
        )
    }
    expected_incoming = _expected_incoming_calls(cfg, finite_internal_edges)
    resolved_writes = tuple(
        row
        for write in sorted(memory_writes, key=_write_key)
        for row in _resolve_formal_write_fact(
            write,
            calls_by_target=calls_by_target,
            expected_incoming=expected_incoming,
            limits=limits,
        )
    )
    terminal_identities: set[tuple[int, int]] = set()
    for row in terminal_external_edges:
        target = getattr(row, "target", None)
        if target is None:
            target = getattr(row, "iat_va", 0)
        terminal_identities.add((getattr(row, "source", -1), int(target)))
    sites: list[HelperEffectSiteEvidence] = []
    gaps: list[ClosureGap] = []
    summary_entry_counts = Counter(row.entry for row in summaries)
    for entry in sorted(
        row for row, count in summary_entry_counts.items() if count != 1
    ):
        gaps.append(
            ClosureGap(
                entry,
                "duplicate-function-summary",
                f"entry={entry:#x}",
            )
        )
    call_key_counts = Counter(_call_key(row) for row in calls)
    for key in sorted(row for row, count in call_key_counts.items() if count != 1):
        gaps.append(
            ClosureGap(
                int(key[0]),
                "duplicate-call-path-fact",
                repr(key),
            )
        )
    semantic_evidence: list[LifecycleSemanticEvidence] = []
    for write in sorted(resolved_writes, key=_write_key):
        pointer_type = write.base.pointer_type
        if pointer_type in {
            "stack",
            "pcode",
            "objobject",
            "arena-allocation",
        }:
            if pointer_type != "stack":
                semantic_evidence.append(
                    LifecycleSemanticEvidence(
                        "typed-storage-write",
                        write.address,
                        0,
                        (pointer_type,),
                        (),
                        (
                            f"write-operation:{write.operation}",
                            f"write-width:{write.width}",
                            f"base-origin:{write.base.origin}",
                        ),
                    )
                )
            continue
        if pointer_type == "image":
            semantic_evidence.append(
                LifecycleSemanticEvidence(
                    "static-storage-write",
                    write.address,
                    0,
                    tuple(
                        sorted(
                            {
                                row
                                for row in (
                                    write.base.pointer_type,
                                    write.value.pointer_type,
                                )
                                if row
                            }
                        )
                    ),
                    (),
                    (
                        f"write-operation:{write.operation}",
                        f"write-width:{write.width}",
                        f"mapped-base:{write.base.pointer_base:#x}",
                    ),
                )
            )
            continue
        if write.base.kind == "pointer" and pointer_type:
            semantic_evidence.append(
                LifecycleSemanticEvidence(
                    "proved-disjoint-typed-storage-write",
                    write.address,
                    0,
                    (pointer_type,),
                    (),
                    (
                        f"write-operation:{write.operation}",
                        f"write-width:{write.width}",
                        f"base-origin:{write.base.origin}",
                    ),
                )
            )
            continue
        gaps.append(
            ClosureGap(
                write.address,
                "helper-storage-effect-unclassified",
                (
                    f"pointer_type={pointer_type or '<unknown>'};"
                    f"operation={write.operation};width={write.width}"
                ),
                (
                    f"base-origin:{write.base.origin}",
                    f"value-origin:{write.value.origin}",
                ),
            )
        )
    obligations = _call_target_obligations(
        cfg, calls, finite_internal_edges, terminal_external_edges
    )
    for address, target in obligations:
        call_paths = tuple(
            sorted(
                (
                    row
                    for row in calls
                    if row.address == address and row.target in {0, target}
                ),
                key=_call_key,
            )
        )
        pointer_types = tuple(
            sorted(
                {
                    argument.pointer_type
                    for row in call_paths
                    for argument in row.arguments
                    if argument.pointer_type
                }
            )
        )
        if target in _ARENA_ALLOCATORS:
            disposition = "arena-allocation"
            summary_entries = allocations = writes = callees = ()
            semantic_evidence.append(
                LifecycleSemanticEvidence(
                    "arena-allocation",
                    address,
                    target,
                    ("arena-allocation",),
                    (target,),
                    (f"accepted-arena-call:{address:#x}->{target:#x}",),
                )
            )
        elif target in summary_map:
            summary_entries, allocations, writes, callees = (
                _transitive_summary_effects(target, summary_map)
            )
            disposition = (
                "internal-summary-effects"
                if allocations or writes
                else "internal-summary-no-effects"
            )
            if allocations or writes or callees:
                semantic_evidence.append(
                    LifecycleSemanticEvidence(
                        "helper-transitive-effects",
                        address,
                        target,
                        pointer_types,
                        (),
                        (
                            *(f"summary-entry:{row:#x}" for row in summary_entries),
                            *(f"allocation-site:{row:#x}" for row in allocations),
                            *(f"write-site:{row:#x}" for row in writes),
                            *(f"transitive-callee:{row:#x}" for row in callees),
                        ),
                    )
                )
        elif (address, target) in terminal_identities:
            disposition = "terminal-external"
            summary_entries = allocations = writes = callees = ()
        else:
            disposition = "unmodelled-call-target"
            summary_entries = allocations = writes = callees = ()
        provenance = (
            f"accepted-call-target:{address:#x}->{target:#x}",
            *(f"call-path-owner:{row.function_entry:#x}" for row in call_paths),
            *(f"summary-entry:{row:#x}" for row in summary_entries),
        )
        sites.append(
            HelperEffectSiteEvidence(
                address,
                target,
                tuple(sorted({row.function_entry for row in call_paths})),
                disposition,
                pointer_types,
                summary_entries,
                allocations,
                writes,
                callees,
                provenance,
            )
        )
        if not call_paths:
            gaps.append(
                ClosureGap(
                    address,
                    "missing-call-path-fact",
                    f"target={target:#x}",
                    provenance,
                )
            )
        if disposition == "unmodelled-call-target":
            gaps.append(
                ClosureGap(
                    address,
                    "call-target-lacks-helper-summary",
                    f"target={target:#x}",
                    provenance,
                )
            )
        if disposition == "terminal-external" and pointer_types:
            gaps.append(
                ClosureGap(
                    address,
                    "typed-pointer-escapes-terminal-helper",
                    f"target={target:#x};types={','.join(pointer_types)}",
                    provenance,
                )
            )
    return LifecycleEffectClosureCertificate(
        compiler_sha256,
        cfg_instruction_hash,
        len({address for address, _target in obligations}),
        tuple(sites),
        tuple(
            sorted(
                semantic_evidence,
                key=lambda row: (row.address, row.kind, row.target, row.provenance),
            )
        ),
        tuple(sorted({row.address for row in resolved_writes})),
        tuple(sorted(summary_map)),
        tuple(sorted(gaps, key=lambda row: (row.address, row.kind, row.detail))),
        _configured_limit_items(limits),
        (
            ("call_target_obligations", len(obligations)),
            ("function_summaries", len(summary_map)),
            ("resolved_storage_effects", len(resolved_writes)),
            ("lifecycle_semantic_facts", len(semantic_evidence)),
            ("helper_effect_gaps", len(gaps)),
        ),
    )


def derive_final_emission_closure(
    *,
    compiler_sha256: str,
    cfg_instruction_hash: str,
    calls: Sequence[CallFact],
    memory_writes: Sequence[MemoryWriteFact],
    limits: AnalysisLimits,
    pseudo_op_dispositions: Sequence[PseudoOpDispositionEvidence] = (),
) -> FinalEmissionClosureCertificate:
    """Derive the singular typed encoder and its downstream output relations."""

    grouped: dict[tuple[int, int, int], tuple[set[int], set[int]]] = {}
    writes_by_owner_value: dict[
        tuple[int, tuple[Any, ...]], set[int]
    ] = defaultdict(set)
    for write in memory_writes:
        if write.value.is_bottom or write.value.is_unknown:
            continue
        writes_by_owner_value[
            (write.function_entry, _abstract_semantic_key(write.value))
        ].add(write.address)
    ordered_write_addresses = {
        key: tuple(sorted(addresses))
        for key, addresses in writes_by_owner_value.items()
    }
    for call in calls:
        key = (call.address, call.target, call.function_entry)
        write_sites, pcode_arguments = grouped.setdefault(key, (set(), set()))
        pcode_arguments.update(
            index
            for index, argument in enumerate(call.arguments)
            if argument.pointer_type == "pcode"
        )
        if not call.return_value.is_bottom and not call.return_value.is_unknown:
            addresses = ordered_write_addresses.get(
                (
                    call.function_entry,
                    _abstract_semantic_key(call.return_value),
                ),
                (),
            )
            write_sites.update(addresses[bisect_right(addresses, call.address) :])
    flows = tuple(
        CallReturnWriteEvidence(
            call_address,
            target,
            owner,
            tuple(sorted(write_sites)),
            tuple(sorted(pcode_arguments)),
            (
                f"call-return:{call_address:#x}->{target:#x}",
                f"owner:{owner:#x}",
                *(f"return-write:{row:#x}" for row in sorted(write_sites)),
            ),
        )
        for (call_address, target, owner), (write_sites, pcode_arguments) in sorted(
            grouped.items()
        )
        if write_sites
    )
    gaps: list[ClosureGap] = []
    semantic: set[EmissionSemanticEvidence] = set()
    def has_bound_pcode_result_dependency(flow: CallReturnWriteEvidence) -> bool:
        paths = tuple(
            row
            for row in calls
            if (row.address, row.target, row.function_entry)
            == (flow.call_address, flow.target, flow.function_entry)
        )
        return bool(paths) and all(
            any(
                dependency.kind == "memory-read"
                and dependency.pointer_type == "pcode"
                and dependency.formal_argument_index is None
                for dependency in row.return_value.dependencies
            )
            for row in paths
        )

    typed_flows = tuple(
        row
        for row in flows
        if row.pcode_argument_indices and has_bound_pcode_result_dependency(row)
    )
    if not typed_flows:
        gaps.append(
            ClosureGap(
                0,
                "missing-typed-pcode-encoder-flow",
                "no call consuming a typed PCode has its result bound to a write",
            )
        )
    typed_targets = {row.target for row in typed_flows}
    if len(typed_targets) > 1:
        gaps.append(
            ClosureGap(
                0,
                "multiple-typed-pcode-encoder-targets",
                "targets=" + ",".join(f"{row:#x}" for row in sorted(typed_targets)),
                tuple(
                    f"typed-flow:{row.call_address:#x}->{row.target:#x}"
                    for row in typed_flows
                ),
            )
        )
    range_evidence = False
    relocation_evidence = False
    machine_evidence = False
    derived_walker = 0
    if len(typed_targets) == 1:
        encoder = next(iter(typed_targets))
        encoder_flows = tuple(row for row in typed_flows if row.target == encoder)
        owners = {row.function_entry for row in encoder_flows}
        if len(owners) != 1:
            gaps.append(
                ClosureGap(
                    0,
                    "multiple-final-walker-owners",
                    "owners=" + ",".join(f"{row:#x}" for row in sorted(owners)),
                )
            )
        else:
            owner = next(iter(owners))
            derived_walker = owner
            semantic.add(
                EmissionSemanticEvidence(
                    "final-pcode-walker",
                    owner,
                    tuple(sorted(row.call_address for row in encoder_flows)),
                    tuple(
                        f"owns-typed-encoder-call:{row.call_address:#x}"
                        for row in encoder_flows
                    ),
                )
            )
        semantic.add(
            EmissionSemanticEvidence(
                "encode-one-final-pcode",
                encoder,
                tuple(sorted(row.call_address for row in encoder_flows)),
                tuple(
                    f"typed-call:{row.call_address:#x}:pcode-args="
                    + ",".join(str(index) for index in row.pcode_argument_indices)
                    for row in encoder_flows
                ),
            )
        )
        for flow in encoder_flows:
            call_paths = tuple(
                row
                for row in calls
                if (row.address, row.target, row.function_entry)
                == (flow.call_address, flow.target, flow.function_entry)
            )
            semantic.add(
                EmissionSemanticEvidence(
                    "per-pcode-encoder-call",
                    flow.call_address,
                    (flow.target, *flow.write_addresses),
                    flow.provenance,
                )
            )
            returns = tuple(row.return_value for row in call_paths)
            matching_writes = tuple(
                write
                for write in memory_writes
                if write.function_entry == flow.function_entry
                and write.address in flow.write_addresses
                and write.base.pointer_type
                not in {"pcode", "objobject", "stack"}
                and not write.base.is_bottom
                and not write.base.is_unknown
                and any(
                    _abstract_semantic_key(write.value)
                    == _abstract_semantic_key(returned)
                    for returned in returns
                )
            )
            if len(matching_writes) != 1:
                gaps.append(
                    ClosureGap(
                        flow.call_address,
                        "non-unique-encoder-result-buffer-write",
                        "writes="
                        + ",".join(f"{row.address:#x}" for row in matching_writes),
                        flow.provenance,
                    )
                )
            else:
                write = matching_writes[0]
                semantic.update(
                    {
                        EmissionSemanticEvidence(
                            "encoder-result-buffer-write",
                            write.address,
                            (flow.call_address,),
                            (
                                f"width:{write.width}",
                                f"base:{write.base.kind}:{write.base.pointer_type}:"
                                f"{write.base.origin}",
                            ),
                        ),
                        EmissionSemanticEvidence(
                            "emitted-code-range",
                            write.address,
                            (flow.call_address,),
                            (
                                f"range-base:{_value_expression(write.base)}",
                                f"range-offset:{write.offset}",
                                f"range-width:{write.width}",
                            ),
                        ),
                    }
                )
                range_evidence = range_evidence or (
                    write.width > 0
                    and not write.base.is_bottom
                    and not write.base.is_unknown
                )

            dependencies = tuple(
                dependency
                for returned in returns
                for dependency in returned.dependencies
            )
            pcode_dependencies = tuple(
                sorted(
                    {
                        row
                        for row in dependencies
                        if row.kind == "memory-read"
                        and row.pointer_type == "pcode"
                        and row.formal_argument_index is None
                    },
                    key=_dependency_key,
                )
            )
            unresolved_dependencies = tuple(
                row
                for row in dependencies
                if row.kind == "memory-read"
                and (
                    row.formal_argument_index is not None
                    or not row.pointer_type
                )
            )
            if pcode_dependencies and not unresolved_dependencies:
                machine_evidence = True
                semantic.add(
                    EmissionSemanticEvidence(
                        "operand-to-machine-field-derivation",
                        flow.target,
                        tuple(row.address for row in pcode_dependencies),
                        tuple(
                            f"pcode-read:{row.address:#x}:offset="
                            f"{row.pointer_offset:#x}:width={row.width}"
                            for row in pcode_dependencies
                        ),
                    )
                )

            later_calls = tuple(
                row
                for row in calls
                if row.function_entry == flow.function_entry
                and row.address > flow.call_address
            )
            consumers: dict[int, set[ValueDependency]] = defaultdict(set)
            later_by_address = {row.address: row for row in later_calls}
            for row in later_calls:
                for argument in row.arguments:
                    consumers[row.address].update(
                        dependency
                        for dependency in argument.dependencies
                        if dependency.kind == "helper-output"
                        and dependency.address == flow.call_address
                    )
            qualified_consumers = tuple(
                address
                for address, dependencies_at_call in sorted(consumers.items())
                if len(
                    {row.source_address for row in dependencies_at_call}
                )
                >= 2
                and len(
                    {row.pointer_offset for row in dependencies_at_call}
                )
                >= 2
                and sum(
                    not argument.is_bottom
                    for argument in later_by_address[address].arguments
                )
                >= 3
            )
            for address in qualified_consumers:
                relocation_evidence = True
                semantic.add(
                    EmissionSemanticEvidence(
                        "relocation-record-consumer",
                        address,
                        (flow.call_address,),
                        tuple(
                            f"encoder-output:{row.source_address:#x}:"
                            f"offset={row.pointer_offset:#x}:width={row.width}"
                            for row in sorted(
                                consumers[address], key=_dependency_key
                            )
                        ),
                    )
                )

    pseudo_evidence = False
    if len(pseudo_op_dispositions) > 1:
        gaps.append(
            ClosureGap(
                derived_walker,
                "duplicate-pseudo-op-disposition-evidence",
                f"rows={len(pseudo_op_dispositions)}",
            )
        )
    elif pseudo_op_dispositions:
        row = pseudo_op_dispositions[0]
        if not isinstance(row, PseudoOpDispositionEvidence):
            gaps.append(
                ClosureGap(
                    derived_walker,
                    "malformed-pseudo-op-disposition-evidence",
                    f"type={type(row).__name__}",
                )
            )
        elif not derived_walker or row.walker_address != derived_walker:
            gaps.append(
                ClosureGap(
                    row.walker_address,
                    "pseudo-op-walker-differs",
                    f"derived={derived_walker:#x};evidence={row.walker_address:#x}",
                    row.provenance,
                )
            )
        else:
            pseudo_evidence = True
            semantic.add(
                EmissionSemanticEvidence(
                    "pseudo-op-disposition",
                    row.walker_address,
                    row.disposition_sites,
                    (
                        f"classification:{row.classification}",
                        "opcode-ids:466,467",
                        *row.provenance,
                    ),
                )
            )
    if not pseudo_evidence:
        gaps.append(
            ClosureGap(
                derived_walker,
                "missing-pseudo-op-disposition-evidence",
                "no exhaustive pseudo-op survival/removal relation was derived",
                tuple(
                    f"typed-flow:{row.call_address:#x}->{row.target:#x}"
                    for row in typed_flows
                ),
            )
        )
    if not range_evidence and not relocation_evidence:
        gaps.append(
            ClosureGap(
                0,
                "missing-emitted-range-relocation-evidence",
                "no unique buffer range or encoder-output relocation consumer",
            )
        )
    elif not range_evidence:
        gaps.append(
            ClosureGap(
                0,
                "missing-emitted-range-evidence",
                "no unique bounded encoder-result buffer write",
            )
        )
    elif not relocation_evidence:
        gaps.append(
            ClosureGap(
                0,
                "missing-relocation-evidence",
                "no later call consumes an exact encoder helper output",
            )
        )
    if not machine_evidence:
        gaps.append(
            ClosureGap(
                0,
                "missing-machine-field-derivation-evidence",
                "encoder result lacks fully bound typed PCode read dependencies",
            )
        )
    return FinalEmissionClosureCertificate(
        compiler_sha256,
        cfg_instruction_hash,
        flows,
        tuple(
            sorted(
                semantic,
                key=lambda row: (
                    row.address,
                    row.kind,
                    row.related_addresses,
                    row.provenance,
                ),
            )
        ),
        tuple(gaps),
        _configured_limit_items(limits),
        (
            ("call_return_write_flows", len(flows)),
            ("emission_semantic_facts", len(semantic)),
            ("final_emission_gaps", len(gaps)),
        ),
    )


def analyze_values(
    image: Image,
    cfg: RawCfg,
    control_targets: ControlTargetResult,
    roots: Sequence[int] = (),
    limits: AnalysisLimits | None = None,
) -> AnalysisResult:
    """Compute bounded function summaries and proof-relevant value facts."""

    limits = limits or AnalysisLimits.for_image(image)
    limits.check("max_instructions", len(cfg.instructions))
    limits.check("max_blocks", len(cfg.blocks))
    limits.check("max_edges", len(cfg.edges))
    jump_tables = tuple(getattr(cfg, "jump_tables", ()))
    limits.check("max_jump_tables", len(jump_tables))
    limits.check(
        "max_jump_table_entries",
        sum(len(getattr(row, "entries", ())) for row in jump_tables),
    )
    targets_by_source: dict[int, set[int]] = defaultdict(set)
    for row in control_targets.finite_internal_edges:
        targets_by_source[row.source].add(row.target)
    limits.check(
        "max_finite_targets",
        max((len(rows) for rows in targets_by_source.values()), default=0),
    )
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
        # An unknown local ESP coordinate is bookkeeping, not by itself a
        # proof-relevant value.  A later relevant call/store retains bottom or
        # unknown provenance and is diagnosed at that consumer instead.
        unresolved.update(
            row
            for row in analysis.unresolved
            if row.reason != "push-with-unknown-esp"
        )
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
    ordered_summaries = tuple(summaries[entry] for entry in sorted(summaries))
    ordered_calls = tuple(sorted(calls, key=_call_key))
    ordered_writes = tuple(sorted(writes, key=_write_key))
    limits.check("max_fixpoint_updates", len(ordered_calls))
    limits.check("max_fixpoint_updates", len(ordered_writes))
    high_water_marks = (
        ("functions", len(functions)),
        ("scc_iterations", scc_iterations),
        ("summary_updates", summary_updates),
        ("block_updates", max_block_updates),
        ("finite_values", max_finite_values),
    )
    alias_write_closure = derive_alias_write_closure(
        cfg,
        compiler_sha256=image.sha256,
        cfg_instruction_hash=instruction_hash,
        memory_writes=ordered_writes,
        calls=ordered_calls,
        finite_internal_edges=control_targets.finite_internal_edges,
        limits=limits,
    )
    lifecycle_effect_closure = derive_lifecycle_effect_closure(
        cfg,
        compiler_sha256=image.sha256,
        cfg_instruction_hash=instruction_hash,
        summaries=ordered_summaries,
        calls=ordered_calls,
        memory_writes=ordered_writes,
        finite_internal_edges=control_targets.finite_internal_edges,
        terminal_external_edges=control_targets.terminal_external_edges,
        limits=limits,
    )
    final_emission_closure = derive_final_emission_closure(
        compiler_sha256=image.sha256,
        cfg_instruction_hash=instruction_hash,
        calls=ordered_calls,
        memory_writes=ordered_writes,
        limits=limits,
        pseudo_op_dispositions=(),
    )
    return AnalysisResult(
        compiler_sha256=image.sha256,
        cfg_instruction_hash=instruction_hash,
        summaries=ordered_summaries,
        calls=ordered_calls,
        memory_writes=ordered_writes,
        finite_internal_edges=control_targets.finite_internal_edges,
        terminal_external_edges=control_targets.terminal_external_edges,
        external_escapes=control_targets.external_escapes,
        unresolved=tuple(sorted(unresolved, key=_unresolved_key)),
        proof_ready=not unresolved,
        limits=limits,
        high_water_marks=high_water_marks,
        alias_write_closure=alias_write_closure,
        lifecycle_effect_closure=lifecycle_effect_closure,
        final_emission_closure=final_emission_closure,
    )
