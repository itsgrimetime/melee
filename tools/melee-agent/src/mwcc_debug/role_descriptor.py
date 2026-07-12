from __future__ import annotations
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from typing import Mapping, Optional
from .colorgraph_parser import parse_hook_events, find_function, FunctionEvents
from .parser import parse_pcdump, analyze_function, Function
from .coalesce_ir_facts import collect, IrFacts
from .first_divergence import select_class_section, decision_views

_REG = re.compile(r"\b([rf])\d+\b")     # rNN/fNN register tokens (virtual or phys)
_REG_NUMBER = re.compile(r"\b([rf])(\d+)\b")
_RELOCATION = re.compile(r"@(\d+)")
_BLOCK_REFERENCE = re.compile(r"\bB(\d+)\b", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_EARLY_SEMANTIC_PASS = "BEFORE GLOBAL OPTIMIZATION"


def normalize_first_def(fd) -> str:
    """Stable first-def signature: opcode + operands with rNN tokens replaced by
    a positional placeholder, lowercased. Keeps offsets/immediates/structure,
    drops volatile register numbers that differ across compiles."""
    if fd is None:
        return ""
    ops = _REG.sub(lambda match: f"{match.group(1)}#", fd.operands.strip().lower())
    return f"{fd.opcode.strip().lower()} {ops}".strip()


def _reg_kind_for_class(class_id: int) -> str:
    if class_id == 0:
        return "r"
    if class_id == 1:
        return "f"
    raise NotImplementedError(f"unsupported register class id: {class_id}")


@dataclass
class Compile:
    """One pcdump's view of a function: colorgraph events + parser Function +
    source + derived IR facts. The identity layer's unit of input."""
    name: str
    fev: FunctionEvents
    fn: Function
    source: str
    ir_facts: IrFacts

    @classmethod
    def from_text(cls, pcdump_text: str, function: str, source: str) -> "Compile":
        fev = find_function(parse_hook_events(pcdump_text), function)
        fn = next((f for f in parse_pcdump(pcdump_text) if f.name == function), None)
        if fev is None or fn is None:
            raise ValueError(f"{function} not found in pcdump")
        return cls(name=function, fev=fev, fn=fn, source=source,
                   ir_facts=collect(fn, source))


@dataclass(frozen=True)
class RoleDescriptor:
    ig_idx: int
    # --- identity-core (decides identity) ---
    first_def_sig: str
    use_site_multiset: tuple                  # sorted ((opcode, count), ...)
    is_param: bool
    var_name: Optional[str]
    var_confidence: Optional[str]
    # --- allocator-state (diagnostic only; never decisive) ---
    assigned_reg: Optional[int]
    live_range: tuple                          # (first_use, last_use)
    use_count: int
    spilled: bool


def _use_multiset(vf) -> tuple:
    c = Counter(ist.opcode.strip().lower() for _blk, ist in (vf.use_sites if vf else []))
    return tuple(sorted(c.items()))


def _semantic_use_multiset(
    c: Compile,
    reg_kind: str,
    ig_idx: int,
    facts,
) -> tuple | None:
    signatures: Counter[tuple[str, str, tuple[str, ...]]] = Counter()
    for _block, instruction in facts.use_sites:
        dependency_owners: dict[tuple[str, bool], tuple[str, int]] = {}
        unresolved = False

        def replace_register(match: re.Match[str]) -> str:
            nonlocal unresolved
            kind = match.group(1).lower()
            number = int(match.group(2))
            if (kind, number) == (reg_kind, ig_idx):
                return f"<{kind}:self>"
            if number < 32:
                return f"<{kind}:physical:{number}>"
            dependency = c.ir_facts.by_reg.get((kind, number))
            if dependency is None or dependency.use_sites_truncated:
                unresolved = True
                return f"<{kind}:unresolved>"
            anchor = (normalize_first_def(dependency.first_def), dependency.is_param)
            if not any(anchor):
                unresolved = True
                return f"<{kind}:unresolved>"
            owner = dependency_owners.setdefault(anchor, (kind, number))
            if owner != (kind, number):
                unresolved = True
                return f"<{kind}:ambiguous>"
            return f"<{kind}:dependency:{anchor[0]}:param={int(anchor[1])}>"

        operands = _REG_NUMBER.sub(
            replace_register,
            instruction.operands.strip().lower(),
        )
        if unresolved:
            return None
        signatures[
            (
                instruction.opcode.strip().lower(),
                _SPACE.sub(" ", operands),
                tuple(_SPACE.sub(" ", item.strip().lower()) for item in instruction.annotations),
            )
        ] += 1
    return tuple(sorted(signatures.items()))


def build_virtual_semantic_identities(
    c: Compile,
    class_id: int,
    virtual_count: int,
) -> dict[int, tuple] | None:
    """Return normalized, allocator-independent identity for every raw IG.

    A complete namespace witness is stronger than the decision-role view used
    by ordinary semantic reanchoring.  It may therefore be emitted only when
    the pre-color IR has untruncated semantic evidence for every raw index.
    """
    reg_kind = _reg_kind_for_class(class_id)
    bindings_by_virtual: dict[int, list] = {}
    if reg_kind == "r":
        for binding in c.ir_facts.bindings:
            bindings_by_virtual.setdefault(binding.virtual, []).append(binding)
    identities: dict[int, tuple] = {}
    for ig_idx in range(virtual_count):
        facts = c.ir_facts.by_reg.get((reg_kind, ig_idx))
        if facts is None or facts.use_sites_truncated:
            return None
        bindings = bindings_by_virtual.get(ig_idx, [])
        strong_names = {
            binding.var_name
            for binding in bindings
            if binding.var_name
            and binding.confidence in {"best-guess", "verified"}
        }
        if len(strong_names) > 1:
            return None
        use_identity = _semantic_use_multiset(c, reg_kind, ig_idx, facts)
        if use_identity is None:
            return None
        identity = (
            normalize_first_def(facts.first_def),
            use_identity,
            facts.is_param,
            next(iter(strong_names), None),
        )
        if not any(identity):
            return None
        identities[ig_idx] = identity
    if len(set(identities.values())) != virtual_count:
        return None
    return identities


def _early_semantic_pass(c: Compile):
    matches = [item for item in c.fn.passes if item.name == _EARLY_SEMANTIC_PASS]
    return matches[0] if len(matches) == 1 else None


def _rank_signatures(signatures: Mapping[tuple, tuple]) -> dict[tuple, int]:
    values = sorted({repr(value) for value in signatures.values()})
    ranks = {value: index for index, value in enumerate(values)}
    return {key: ranks[repr(value)] for key, value in signatures.items()}


def _partition(colors: Mapping[tuple, int]) -> frozenset[frozenset[tuple]]:
    groups: dict[int, set[tuple]] = defaultdict(set)
    for key, color in colors.items():
        groups[color].add(key)
    return frozenset(frozenset(group) for group in groups.values())


@dataclass(frozen=True)
class _BlockPairing:
    candidate_to_reference: Mapping[int, int]
    reference_canonical: Mapping[int, int]
    candidate_canonical: Mapping[int, int]


def _cfg_block_map(reference_pass, candidate_pass) -> _BlockPairing | None:
    sides = (
        {block.index: block for block in reference_pass.blocks},
        {block.index: block for block in candidate_pass.blocks},
    )
    if (
        not sides[0]
        or len(sides[0]) != len(reference_pass.blocks)
        or len(sides[1]) != len(candidate_pass.blocks)
        or len(sides[0]) != len(sides[1])
    ):
        return None
    if any(
        edge not in blocks
        for blocks in sides
        for block in blocks.values()
        for edge in (*block.pred, *block.succ)
    ):
        return None
    colors = _rank_signatures(
        {
            (side, block.index): (
                len(block.pred),
                len(block.succ),
                len(block.labels),
                not block.pred,
                not block.succ,
                _block_instruction_skeletons(block),
            )
            for side, blocks in enumerate(sides)
            for block in blocks.values()
        }
    )
    for _iteration in range(len(sides[0]) + 1):
        signatures = {
            (side, block.index): (
                len(block.pred),
                len(block.succ),
                len(block.labels),
                not block.pred,
                not block.succ,
                _block_instruction_skeletons(block),
                tuple(sorted(colors[(side, item)] for item in block.pred)),
                tuple(sorted(colors[(side, item)] for item in block.succ)),
            )
            for side, blocks in enumerate(sides)
            for block in blocks.values()
            if all((side, item) in colors for item in (*block.pred, *block.succ))
        }
        if len(signatures) != len(colors):
            return None
        refined = _rank_signatures(signatures)
        stable = _partition(refined) == _partition(colors)
        colors = refined
        if stable:
            break
    else:
        return None
    by_side: list[dict[int, list[int]]] = []
    for side in (0, 1):
        groups: dict[int, list[int]] = defaultdict(list)
        for (entry_side, block_idx), color in colors.items():
            if entry_side == side:
                groups[color].append(block_idx)
        by_side.append(groups)
    if by_side[0].keys() != by_side[1].keys() or any(
        len(by_side[0][color]) != 1 or len(by_side[1][color]) != 1
        for color in by_side[0]
    ):
        return None
    result = {
        by_side[1][color][0]: by_side[0][color][0]
        for color in by_side[0]
    }
    if len(result) != len(sides[0]):
        return None
    for candidate_idx, reference_idx in result.items():
        candidate_block = sides[1][candidate_idx]
        reference_block = sides[0][reference_idx]
        if (
            {result[item] for item in candidate_block.pred} != set(reference_block.pred)
            or {result[item] for item in candidate_block.succ} != set(reference_block.succ)
        ):
            return None
    return _BlockPairing(
        candidate_to_reference=result,
        reference_canonical={
            block_idx: color
            for color, (block_idx,) in by_side[0].items()
        },
        candidate_canonical={
            block_idx: color
            for color, (block_idx,) in by_side[1].items()
        },
    )


def _instruction_skeleton(instruction, *, normalize_relocation: bool) -> tuple:
    def replace_register(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        number = int(match.group(2))
        return f"<{kind}:physical:{number}>" if number < 32 else f"<{kind}:virtual>"

    operands = instruction.operands.strip().lower()
    operands = _BLOCK_REFERENCE.sub("<block>", operands)
    if normalize_relocation:
        operands = _RELOCATION.sub("<relocation-family>", operands)
    return (
        instruction.opcode.strip().lower(),
        _SPACE.sub(" ", _REG_NUMBER.sub(replace_register, operands)),
        tuple(_SPACE.sub(" ", item.strip().lower()) for item in instruction.annotations),
    )


def _block_instruction_skeletons(block) -> tuple[tuple, ...]:
    relocation_families = {
        family
        for instruction in block.instructions
        for family in _RELOCATION.findall(instruction.operands)
    }
    normalize_relocation = len(relocation_families) <= 1
    return tuple(
        _instruction_skeleton(
            instruction,
            normalize_relocation=normalize_relocation,
        )
        for instruction in block.instructions
    )


def _observed_virtuals(semantic_pass) -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    for block in semantic_pass.blocks:
        for instruction in block.instructions:
            for kind, number in instruction.regs:
                if number >= 32:
                    result[kind].add(number)
    return result


def _normalized_occurrences(
    semantic_pass,
    canonical_blocks: Mapping[int, int],
    virtual_maps: Mapping[str, Mapping[int, int]],
    *,
    reference: bool,
) -> dict[tuple[str, int], tuple] | None:
    occurrences: dict[tuple[str, int], list[tuple]] = defaultdict(list)
    for block in semantic_pass.blocks:
        if block.index not in canonical_blocks:
            return None
        canonical_block = canonical_blocks[block.index]
        relocation_families = {
            family
            for instruction in block.instructions
            for family in _RELOCATION.findall(instruction.operands)
        }
        normalize_relocation = len(relocation_families) <= 1
        for instruction_ordinal, instruction in enumerate(block.instructions):
            unresolved = False

            def replace_register(match: re.Match[str]) -> str:
                nonlocal unresolved
                kind = match.group(1).lower()
                number = int(match.group(2))
                if number < 32:
                    return f"<{kind}:physical:{number}>"
                kind_map = virtual_maps.get(kind)
                canonical = (
                    number
                    if reference
                    else kind_map.get(number)
                    if kind_map
                    else None
                )
                if canonical is None:
                    unresolved = True
                    return f"<{kind}:unresolved>"
                return f"<{kind}:role:{canonical}>"

            def replace_block(match: re.Match[str]) -> str:
                nonlocal unresolved
                raw_block = int(match.group(1))
                canonical = canonical_blocks.get(raw_block)
                if canonical is None:
                    unresolved = True
                    return "<block:unresolved>"
                return f"<block:{canonical}>"

            operands = instruction.operands.strip().lower()
            if normalize_relocation:
                operands = _RELOCATION.sub("<relocation-family>", operands)
            operands = _BLOCK_REFERENCE.sub(replace_block, operands)
            normalized_instruction = (
                instruction.opcode.strip().lower(),
                _SPACE.sub(" ", _REG_NUMBER.sub(replace_register, operands)),
                tuple(
                    _SPACE.sub(" ", item.strip().lower())
                    for item in instruction.annotations
                ),
            )
            if unresolved:
                return None
            for operand_ordinal, (kind, number) in enumerate(instruction.regs):
                if number < 32:
                    continue
                canonical = number if reference else virtual_maps[kind][number]
                occurrences[(kind, canonical)].append(
                    (
                        canonical_block,
                        instruction_ordinal,
                        operand_ordinal,
                        normalized_instruction,
                    )
                )
    return {role: tuple(sorted(items)) for role, items in occurrences.items()}


def prove_virtual_namespace_map(
    reference: Compile,
    candidate: Compile,
    class_id: int,
    virtual_count: int,
    reviewed: Mapping[int, int] | None = None,
) -> dict[int, int] | None:
    """Prove a complete candidate-IG to reference-IG bijection pairwise."""
    reg_kind = _reg_kind_for_class(class_id)
    reference_sections = [
        section for section in reference.fev.coalesce_sections if section.class_id == class_id
    ]
    candidate_sections = [
        section for section in candidate.fev.coalesce_sections if section.class_id == class_id
    ]
    if (
        virtual_count < 32
        or not reference_sections
        or not candidate_sections
        or reference_sections[-1].n_virtuals != virtual_count
        or candidate_sections[-1].n_virtuals != virtual_count
    ):
        return None
    reference_pass = _early_semantic_pass(reference)
    candidate_pass = _early_semantic_pass(candidate)
    if reference_pass is None or candidate_pass is None:
        return None
    block_pairing = _cfg_block_map(reference_pass, candidate_pass)
    if block_pairing is None:
        return None
    domain = set(range(32, virtual_count))
    reviewed_map = dict(reviewed or {})
    if (
        any(key not in domain or value not in domain for key, value in reviewed_map.items())
        or len(set(reviewed_map.values())) != len(reviewed_map)
    ):
        return None
    reference_blocks = {block.index: block for block in reference_pass.blocks}
    candidate_blocks = {block.index: block for block in candidate_pass.blocks}
    reference_observed = _observed_virtuals(reference_pass)
    candidate_observed = _observed_virtuals(candidate_pass)
    if reference_observed.get(reg_kind, set()) != domain or candidate_observed.get(reg_kind, set()) != domain:
        return None
    candidate_to_reference: dict[str, dict[int, int]] = defaultdict(dict)
    reference_to_candidate: dict[str, dict[int, int]] = defaultdict(dict)
    for candidate_block_idx, reference_block_idx in block_pairing.candidate_to_reference.items():
        reference_block = reference_blocks[reference_block_idx]
        candidate_block = candidate_blocks[candidate_block_idx]
        reference_skeletons = _block_instruction_skeletons(reference_block)
        candidate_skeletons = _block_instruction_skeletons(candidate_block)
        if reference_skeletons != candidate_skeletons:
            return None
        for reference_instruction, candidate_instruction in zip(
            reference_block.instructions,
            candidate_block.instructions,
            strict=True,
        ):
            if len(reference_instruction.regs) != len(candidate_instruction.regs):
                return None
            for reference_reg, candidate_reg in zip(
                reference_instruction.regs,
                candidate_instruction.regs,
                strict=True,
            ):
                if reference_reg[0] != candidate_reg[0]:
                    return None
                kind = reference_reg[0]
                reference_ig = reference_reg[1]
                candidate_ig = candidate_reg[1]
                if reference_ig < 32 or candidate_ig < 32:
                    if reference_ig != candidate_ig or (reference_ig < 32) != (candidate_ig < 32):
                        return None
                    continue
                if (
                    candidate_ig in candidate_to_reference[kind]
                    and candidate_to_reference[kind][candidate_ig] != reference_ig
                    or reference_ig in reference_to_candidate[kind]
                    and reference_to_candidate[kind][reference_ig] != candidate_ig
                ):
                    return None
                candidate_to_reference[kind][candidate_ig] = reference_ig
                reference_to_candidate[kind][reference_ig] = candidate_ig
    for kind in reference_observed.keys() | candidate_observed.keys():
        if (
            set(candidate_to_reference[kind]) != candidate_observed.get(kind, set())
            or set(candidate_to_reference[kind].values()) != reference_observed.get(kind, set())
            or len(reference_to_candidate[kind]) != len(reference_observed.get(kind, set()))
        ):
            return None
    if (
        set(candidate_to_reference[reg_kind]) != domain
        or set(candidate_to_reference[reg_kind].values()) != domain
        or any(candidate_to_reference[reg_kind].get(key) != value for key, value in reviewed_map.items())
    ):
        return None
    reference_occurrences = _normalized_occurrences(
        reference_pass,
        block_pairing.reference_canonical,
        candidate_to_reference,
        reference=True,
    )
    candidate_occurrences = _normalized_occurrences(
        candidate_pass,
        block_pairing.candidate_canonical,
        candidate_to_reference,
        reference=False,
    )
    if reference_occurrences is None or candidate_occurrences is None:
        return None
    for kind, kind_map in candidate_to_reference.items():
        for candidate_ig, reference_ig in kind_map.items():
            if candidate_occurrences.get((kind, reference_ig)) != reference_occurrences.get(
                (kind, reference_ig)
            ):
                return None
    return {
        **{physical: physical for physical in range(32)},
        **dict(sorted(candidate_to_reference[reg_kind].items())),
    }


def build_descriptors(c: Compile, class_id: int) -> dict:
    """One RoleDescriptor per class-`class_id` decision node (ig >= 0)."""
    section = select_class_section(c.fev, class_id)
    if section is None:
        return {}
    reg_kind = _reg_kind_for_class(class_id)
    views = {v.ig_idx: v for v in decision_views(section, c.fev) if v.ig_idx >= 0}
    reg_info = {
        (getattr(vi, "reg_kind", "r"), vi.virtual): vi
        for vi in analyze_function(c.fn)
    }
    bind = {b.virtual: b for b in c.ir_facts.bindings} if reg_kind == "r" else {}
    out: dict = {}
    for ig, v in views.items():
        vf = c.ir_facts.by_reg.get((reg_kind, ig))
        if vf is None and reg_kind == "r":
            vf = c.ir_facts.by_virtual.get(ig)
        ri = reg_info.get((reg_kind, ig))
        b = bind.get(ig)
        out[ig] = RoleDescriptor(
            ig_idx=ig,
            first_def_sig=normalize_first_def(vf.first_def if vf else None),
            use_site_multiset=_use_multiset(vf),
            is_param=bool(vf.is_param) if vf else False,
            var_name=(b.var_name if b else None),
            var_confidence=(b.confidence if b else None),
            assigned_reg=v.assigned_reg,
            live_range=((ri.first_use, ri.last_use) if ri else (-1, -1)),
            use_count=(ri.use_count if ri else 0),
            spilled=v.spilled,
        )
    return out


@dataclass(frozen=True)
class TargetRoleSpec:
    original_ig: int
    desired_phys: int
    class_id: int
    descriptor: RoleDescriptor
    role_order_rank: Optional[int]            # None for structural (Case D/E) roles


@dataclass(frozen=True)
class TargetSpec:
    function: str
    target_kind: str                          # "force_proof_proxy" | "matched_natural"
    target_coverage: float
    causal_closure: bool
    provenance: dict
    roles: list

    def save_json(self, path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=list))

    @classmethod
    def load_json(cls, path) -> "TargetSpec":
        d = json.loads(path.read_text())
        roles = []
        for r in d["roles"]:
            rdesc = r["descriptor"]
            desc = None if rdesc is None else RoleDescriptor(**{**rdesc,
                "use_site_multiset": tuple(tuple(x) for x in rdesc["use_site_multiset"]),
                "live_range": tuple(rdesc["live_range"])})
            roles.append(TargetRoleSpec(
                original_ig=r["original_ig"], desired_phys=r["desired_phys"],
                class_id=r["class_id"], role_order_rank=r["role_order_rank"],
                descriptor=desc))
        return cls(function=d["function"], target_kind=d["target_kind"],
                   target_coverage=d["target_coverage"], causal_closure=d["causal_closure"],
                   provenance=d["provenance"], roles=roles)


def build_target_spec(c: Compile, force_phys: dict, class_id: int,
                      target_kind: str, provenance: dict,
                      causal_closure: bool = False) -> TargetSpec:
    descs = build_descriptors(c, class_id)
    section = select_class_section(c.fev, class_id)
    rank = {v.ig_idx: i for i, v in enumerate(
        sorted((vv for vv in decision_views(section, c.fev) if vv.ig_idx >= 0),
               key=lambda d: d.iter_idx))} if section else {}
    roles = []
    for ig, phys in force_phys.items():
        roles.append(TargetRoleSpec(
            original_ig=ig, desired_phys=phys, class_id=class_id,
            descriptor=descs.get(ig),            # None if coalesced/spilled (structural)
            role_order_rank=rank.get(ig)))
    n_decisions = len(rank) or 1
    coverage = round(len([r for r in roles if r.role_order_rank is not None]) / n_decisions, 3)
    return TargetSpec(function=c.name, target_kind=target_kind, target_coverage=coverage,
                      causal_closure=causal_closure, provenance=provenance, roles=roles)
