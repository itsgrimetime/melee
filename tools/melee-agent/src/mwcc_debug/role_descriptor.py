from __future__ import annotations
import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Optional
from .colorgraph_parser import parse_hook_events, find_function, FunctionEvents
from .parser import parse_pcdump, analyze_function, Function
from .coalesce_ir_facts import collect, IrFacts
from .first_divergence import select_class_section, decision_views

_REG = re.compile(r"\br\d+\b")          # rNN register tokens (virtual or phys)


def normalize_first_def(fd) -> str:
    """Stable first-def signature: opcode + operands with rNN tokens replaced by
    a positional placeholder, lowercased. Keeps offsets/immediates/structure,
    drops volatile register numbers that differ across compiles."""
    if fd is None:
        return ""
    ops = _REG.sub("r#", fd.operands.strip().lower())
    return f"{fd.opcode.strip().lower()} {ops}".strip()


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


def build_descriptors(c: Compile, class_id: int) -> dict:
    """One RoleDescriptor per class-`class_id` decision node (ig >= 0).

    reg_info and bindings are keyed by virtual number under the class-0/GPR
    assumption: analyze_function and IrFacts.by_virtual only track GPR "r"
    operands. For a non-GPR class those lookups would return GPR data that
    happens to share the ig number — silent pollution — so this refuses any
    class other than 0 until the maps are made class-aware (carry-forward #2)."""
    section = select_class_section(c.fev, class_id)
    if section is None:
        return {}
    if class_id != 0:
        raise NotImplementedError(
            f"build_descriptors supports only class 0 (GPR); got class_id="
            f"{class_id}. analyze_function/ir_facts are GPR-keyed, so non-GPR "
            f"ig lookups would be polluted by GPR data sharing the ig number. "
            f"Make reg_info/bindings class-aware before matching non-GPR classes."
        )
    views = {v.ig_idx: v for v in decision_views(section, c.fev) if v.ig_idx >= 0}
    reg_info = {vi.virtual: vi for vi in analyze_function(c.fn)}
    bind = {b.virtual: b for b in c.ir_facts.bindings}
    out: dict = {}
    for ig, v in views.items():
        vf = c.ir_facts.by_virtual.get(ig)
        ri = reg_info.get(ig)
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
