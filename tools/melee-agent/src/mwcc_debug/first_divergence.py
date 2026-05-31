"""First-divergence analyzer (v1, same-source).

Reads structured colorgraph events (colorgraph_parser.parse_hook_events) and a
force-phys target map, finds the earliest allocator decision that diverges from
target, explains it mechanically, and (optionally) attaches advisory source
ideas. See docs/superpowers/specs/2026-05-27-first-divergence-analyzer-design.md.

The parser-coupled accessors are kept small and isolated (`decision_views`,
`_present_ig_idxs`, `_coalesce_root`, `_is_spilled`); everything else operates on
the local DecisionView / ReplayStep / AllocatorFact types so the logic is
unit-testable in isolation.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Mapping, NamedTuple, Optional

from .simulator import INITIAL_VOLATILE_REGS, NONVOLATILE_ALLOC_ORDER, RESERVED_REGS

if TYPE_CHECKING:
    from .colorgraph_parser import ColorgraphSection, FunctionEvents


class DecisionView(NamedTuple):
    ig_idx: int
    iter_idx: int
    assigned_reg: int
    n_interferers: int
    interferers: tuple[tuple[int, int], ...]
    spilled: bool


class DivergenceCase(enum.Enum):
    A_BLOCKED = "A"
    B_TARGET_HIGHER = "B"
    B_INVERSE = "B-inverse"
    C_DISPENSE_ORDER = "C"
    C2_STICKY_POOL = "C2"
    D_COALESCED = "D"
    E_SPILLED = "E"
    ABSENT = "absent"
    ABSTAINED = "abstained"  # can't classify: cap-hit / incomplete table / r0 boundary
    NONE = "none"            # all target nodes already on-target; no divergence


@dataclass(frozen=True)
class SourceIdea:                    # the ADVISORY layer (Task 9 fills it)
    ig_idx: int
    var_name: Optional[str]
    confidence: Optional[str]
    alternates: tuple[str, ...]
    ideas: tuple[str, ...]
    rejected: tuple[str, ...] = ()
    first_def: Optional[str] = None
    blocker_ig: Optional[int] = None
    blocker_var_name: Optional[str] = None
    blocker_confidence: Optional[str] = None
    blocker_alternates: tuple[str, ...] = ()
    blocker_rejected: tuple[str, ...] = ()
    blocker_first_def: Optional[str] = None


@dataclass(frozen=True)
class AllocatorFact:                 # the GATED layer
    class_id: int
    ig_idx: int
    case: DivergenceCase
    iter_idx: Optional[int]          # None for pre-walk structural cases
    baseline_reg: Optional[int]
    target_reg: Optional[int]
    coalesced_nodes: tuple[int, ...] # Case D: all target nodes sharing this coalesce
    coalesced_root: Optional[int]
    coalesced_root_phys: Optional[int]
    blocker_ig: Optional[int]        # Case A: interferer holding r_target
    blocker_dependency: bool         # Case A: that interferer is itself off-target
    working_mask: Optional[frozenset[int]]
    cap_hit: bool
    earlier_unmapped_warning: bool   # partial-map caveat
    local_target: str


@dataclass(frozen=True)
class FirstDivergenceReport:
    fact: AllocatorFact
    source: Optional["SourceIdea"]


def is_cap_hit(view: DecisionView) -> bool:
    """True when the dump truncated this decision's interferer row."""
    return len(view.interferers) < view.n_interferers


@dataclass(frozen=True)
class TargetColoring:
    class_id: int
    force_phys: Mapping[int, int]


def target_identity_set(target: "TargetColoring") -> set[int]:
    """The set of target nodes is the force-phys map KEYS (not the forced dump's
    surviving nodes) — coalesced-away nodes must remain in this set so Step 1a
    can detect them (Case D)."""
    return set(target.force_phys.keys())


def select_class_section(fev: "FunctionEvents", class_id: int) -> Optional["ColorgraphSection"]:
    """Return the FINAL colorgraph section for the class (last wins, in case of
    spill-retry sections), or None."""
    matches = [s for s in fev.colorgraph_sections if s.class_id == class_id]
    return matches[-1] if matches else None


def _simplify_section(fev: "FunctionEvents", class_id: int):
    matches = [s for s in fev.simplify_sections if s.class_id == class_id]
    return matches[-1] if matches else None


def local_target_for(case: "DivergenceCase", *, coalesced_nodes=(), root=None,
                     blocker_ig=None, blocker_dependency=False) -> str:
    if case is DivergenceCase.D_COALESCED:
        nodes = ", ".join(str(n) for n in coalesced_nodes)
        return (f"prevent the coalesce that merges node(s) {nodes} into root "
                f"{root} (shorten/separate the live ranges MWCC is merging)")
    if case is DivergenceCase.E_SPILLED:
        return ("reduce X's interference degree so it colors cleanly "
                "(shrink/split the live range)")
    if case is DivergenceCase.ABSENT:
        return ("structural mismatch (wrong class or pair-register constraint); "
                "no single local lever")
    if case is DivergenceCase.A_BLOCKED:
        if blocker_dependency:
            return (f"recolor the upstream blocker (ig {blocker_ig}) first — X's "
                    f"divergence is downstream of it")
        return (f"eliminate the X-Y interference (ig {blocker_ig}) by shortening "
                f"one live range, or process X before Y")
    if case is DivergenceCase.B_TARGET_HIGHER:
        return ("introduce interference with the holders of the registers below "
                "r_target, or move X later in simplify order")
    if case is DivergenceCase.B_INVERSE:
        return ("reduce X's interference, or process X earlier so it isn't pushed "
                "higher than target")
    if case is DivergenceCase.C_DISPENSE_ORDER:
        return "shift X's simplify-order position so dispense reaches r_target"
    if case is DivergenceCase.C2_STICKY_POOL:
        return ("change how many nonvolatiles dispense before X (reorder upstream "
                "virtuals) so r_target is in the sticky pool by X's turn")
    return case.value


def decision_views(section: "ColorgraphSection", fev: "FunctionEvents") -> list[DecisionView]:
    """Adapter: the sole accessor of per-decision parser FIELDS (ColorgraphDecision
    / SimplifyEntry). The section selectors `select_class_section` /
    `_simplify_section` only index the FunctionEvents section lists."""
    simp = _simplify_section(fev, section.class_id)
    spilled_igs = {e.ig_idx for e in (simp.entries if simp else []) if e.spilled}
    return [
        DecisionView(
            ig_idx=d.ig_idx,
            iter_idx=d.iter_idx,
            assigned_reg=d.assigned_reg,
            n_interferers=d.n_interferers,
            interferers=tuple(d.interferers),
            # Spill is taken solely from the simplify section's authoritative
            # SPILLED marker (flags & 0x08), which the parser itself uses. The
            # colorgraph decision row's flags use a different encoding (observed
            # 0x2) whose bit-0 is not a reliable spill bit, so we do not use it.
            spilled=(d.ig_idx in spilled_igs),
        )
        for d in section.decisions
    ]


def decision_coloring(fev, class_id: int) -> dict[int, int]:
    """The faithful, force-phys-safe coloring for a class: each independently
    colored decision node's ig_idx -> assigned physical, read from the raw
    COLORGRAPH DECISIONS (the representation this analyzer consumes).

    Use this — NOT `target derive`'s analyze_function reconstruction — to build a
    same-source target. analyze_function recovers physicals by aligning the
    AFTER-REGISTER-COLORING asm and majority-voting, a different stage that
    disagrees with the raw decisions for coalesced / spilled / r0 nodes, so a
    target built from it does not round-trip cleanly against this analyzer.

    Excludes: the -1 sentinel, spilled nodes, and anything not assigned a real
    register r1..r31 (notably r0, which the replay treats as a model boundary).
    Coalesced aliases are naturally absent (they have no independent decision)."""
    section = select_class_section(fev, class_id)
    if section is None:
        return {}
    return {
        v.ig_idx: v.assigned_reg
        for v in decision_views(section, fev)
        if v.ig_idx >= 0 and 0 < v.assigned_reg <= 31 and not v.spilled
    }


def _present_ig_idxs(fev, class_id: int) -> set[int]:
    section = select_class_section(fev, class_id)
    if section is None:
        return set()
    return {d.ig_idx for d in section.decisions if d.ig_idx >= 0}


def _coalesce_root(fev, class_id: int, ig_idx: int):
    """Return (root_idx, root_phys) if ig_idx was coalesced, else None. Prefers
    the final CoalescedAliasSection (carries root_phys); falls back to the
    CoalesceSection mappings (no phys)."""
    for sec in fev.coalesced_alias_sections:
        if sec.class_id != class_id:
            continue
        for (alias_idx, root_idx, root_phys) in sec.aliases:
            if alias_idx == ig_idx:
                return (root_idx, root_phys)
    for sec in getattr(fev, "coalesce_sections", []):
        if sec.class_id != class_id:
            continue
        for (alias_ig, root_ig) in sec.mappings:
            if alias_ig == ig_idx:
                return (root_ig, None)
    return None


def _is_spilled(fev, class_id: int, ig_idx: int) -> bool:
    for sec in fev.simplify_sections:
        if sec.class_id != class_id:
            continue
        for e in sec.entries:
            if e.ig_idx == ig_idx and e.spilled:
                return True
    return False


def find_absent_targets(fev, target: TargetColoring) -> Optional[AllocatorFact]:
    """Step 1a. For each target node (force-phys key) not present as an
    independent colorgraph node, classify Case D (coalesced) / E (spilled) /
    absent. Coalesced nodes sharing a root are reported together as one fact.
    When missing nodes span multiple distinct coalesce roots, the root of the
    lowest-numbered missing node is reported (one finding at a time, per the
    first-divergence contract).
    Returns None when every target node is present (proceed to Step 1b)."""
    present = _present_ig_idxs(fev, target.class_id)
    missing = [ig for ig in sorted(target_identity_set(target)) if ig not in present]
    if not missing:
        return None

    coalesced: dict[tuple[int, Optional[int]], list[int]] = {}
    spilled: list = []
    truly_absent: list = []
    for ig in missing:
        root = _coalesce_root(fev, target.class_id, ig)
        if root is not None:
            root_idx, root_phys = root
            # On-target via coalescing: the node was merged into a root that
            # already holds this node's TARGET register, so it is satisfied —
            # NOT a Case D divergence. (gm stays Case D: its root holds r3 but
            # the target wants r28.) A natural-self target derived from the dump
            # names each alias at its root's phys, so without this check every
            # coalesced node is a false-positive Case D.
            if root_phys is not None and root_phys == target.force_phys[ig]:
                continue
            coalesced.setdefault((root_idx, root_phys), []).append(ig)
        elif _is_spilled(fev, target.class_id, ig):
            spilled.append(ig)
        else:
            truly_absent.append(ig)

    if not (coalesced or spilled or truly_absent):
        return None  # every missing target node was satisfied via coalescing

    if coalesced:
        (root_idx, root_phys), nodes = next(iter(coalesced.items()))
        nodes_sorted = tuple(sorted(nodes))
        return AllocatorFact(
            class_id=target.class_id, ig_idx=nodes_sorted[0],
            case=DivergenceCase.D_COALESCED, iter_idx=None,
            baseline_reg=root_phys, target_reg=target.force_phys[nodes_sorted[0]],
            coalesced_nodes=nodes_sorted, coalesced_root=root_idx,
            coalesced_root_phys=root_phys, blocker_ig=None,
            blocker_dependency=False, working_mask=None, cap_hit=False,
            earlier_unmapped_warning=False,
            local_target=local_target_for(DivergenceCase.D_COALESCED,
                                          coalesced_nodes=nodes_sorted,
                                          root=root_idx),
        )
    if spilled:
        ig = spilled[0]
        return AllocatorFact(
            class_id=target.class_id, ig_idx=ig, case=DivergenceCase.E_SPILLED,
            iter_idx=None, baseline_reg=None, target_reg=target.force_phys[ig],
            coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
            blocker_ig=None, blocker_dependency=False, working_mask=None,
            cap_hit=False, earlier_unmapped_warning=False,
            local_target=local_target_for(DivergenceCase.E_SPILLED),
        )
    ig = truly_absent[0]
    return AllocatorFact(
        class_id=target.class_id, ig_idx=ig, case=DivergenceCase.ABSENT,
        iter_idx=None, baseline_reg=None, target_reg=target.force_phys[ig],
        coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
        blocker_ig=None, blocker_dependency=False, working_mask=None,
        cap_hit=False, earlier_unmapped_warning=False,
        local_target=local_target_for(DivergenceCase.ABSENT),
    )


class DivergencePoint(NamedTuple):
    ig_idx: int
    iter_idx: int
    baseline_reg: int
    target_reg: int


@dataclass(frozen=True)
class ReplayStep:
    ig_idx: int
    iter_idx: int
    working_mask: frozenset[int]
    predicted_reg: int
    dispensed: bool
    cap_hit: bool
    blockers: frozenset[int]
    unreliable: bool   # blocker set not trustworthy (incomplete decision table)


def find_register_choice_divergence(views, target: TargetColoring
                                    ) -> Optional["DivergencePoint"]:
    """Step 1b. Walk decisions in iter order; return the first force-phys node
    whose assigned_reg != its target reg. Only nodes present in `views` are
    compared (Step 1a already removed absent ones). Returns None if all mapped
    nodes are on target."""
    for v in sorted(views, key=lambda d: d.iter_idx):
        if v.ig_idx in target.force_phys:
            want = target.force_phys[v.ig_idx]
            if v.assigned_reg != want:
                return DivergencePoint(v.ig_idx, v.iter_idx, v.assigned_reg, want)
    return None


_CALLEE_SAVE = set(NONVOLATILE_ALLOC_ORDER)  # {13..31}


def classify_divergence(point: "DivergencePoint", step: ReplayStep,
                        target: TargetColoring, views_by_ig: dict,
                        interferers: tuple) -> AllocatorFact:
    """Classify the divergence at point X using its replayed ReplayStep.
    Ordering matters: the dispensed / volatile-target checks must precede the
    `base > want` fallback, or a dispensed Case C misclassifies as B-inverse."""
    base, want = point.baseline_reg, point.target_reg
    blocker_ig = None
    blocker_dependency = False
    case: DivergenceCase

    if want in step.blockers:
        case = DivergenceCase.A_BLOCKED
        for (i_ig, i_reg) in interferers:
            if i_reg == want:
                blocker_ig = i_ig
                if i_ig in target.force_phys:
                    v = views_by_ig.get(i_ig)
                    if v is not None and v.assigned_reg != target.force_phys[i_ig]:
                        blocker_dependency = True
                break
    elif want in step.working_mask:
        # target was AVAILABLE at X but baseline picked another register
        case = (DivergenceCase.B_TARGET_HIGHER if want > base
                else DivergenceCase.B_INVERSE)
    elif want in INITIAL_VOLATILE_REGS:
        # target is a volatile that wasn't free at X; baseline ended higher
        # (too much interference / processed too late) -> reduce interference.
        # Must precede the dispense cases: a dispensed nonvolatile baseline with
        # a *volatile* target is B-inverse, not C.
        case = DivergenceCase.B_INVERSE
    elif step.dispensed and want in _CALLEE_SAVE and _dispensed_later(
            want, views_by_ig, point.iter_idx):
        case = DivergenceCase.C2_STICKY_POOL
    else:
        case = DivergenceCase.C_DISPENSE_ORDER

    return AllocatorFact(
        class_id=target.class_id, ig_idx=point.ig_idx, case=case,
        iter_idx=point.iter_idx, baseline_reg=base, target_reg=want,
        coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
        blocker_ig=blocker_ig, blocker_dependency=blocker_dependency,
        working_mask=step.working_mask, cap_hit=step.cap_hit,
        earlier_unmapped_warning=False,
        local_target=local_target_for(case, blocker_ig=blocker_ig,
                                      blocker_dependency=blocker_dependency),
    )


def _dispensed_later(reg: int, views_by_ig: dict, after_iter: int) -> bool:
    """True if some decision after `after_iter` was assigned `reg` (a callee-save),
    implying the target coloring could have it sticky-pooled by X's iteration."""
    return any(v.assigned_reg == reg and v.iter_idx > after_iter
               for v in views_by_ig.values())


def analyze_first_divergence(fev, target: TargetColoring) -> FirstDivergenceReport:
    """Gated pipeline: Step 1a -> 1b -> 2 -> classify. `.source` stays None here;
    Task 9's attach_source_ideas fills it on request. Abstains (ABSTAINED) when
    the divergence can't be trusted: a cap-hit or unreliable replay step, or a
    divergence involving r0 (a model boundary the replay cannot predict)."""
    # Step 1a — structural pre-pass.
    absent = find_absent_targets(fev, target)
    if absent is not None:
        return FirstDivergenceReport(fact=absent, source=None)

    section = select_class_section(fev, target.class_id)
    if section is None:
        raise ValueError(f"no colorgraph section for class {target.class_id}")
    views = decision_views(section, fev)
    views_by_ig = {v.ig_idx: v for v in views if v.ig_idx >= 0}

    # Step 1b — register-choice walk.
    point = find_register_choice_divergence(views, target)
    if point is None:
        return FirstDivergenceReport(
            fact=AllocatorFact(
                class_id=target.class_id, ig_idx=-1, case=DivergenceCase.NONE,
                iter_idx=None, baseline_reg=None, target_reg=None,
                coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
                blocker_ig=None, blocker_dependency=False, working_mask=None,
                cap_hit=False, earlier_unmapped_warning=False,
                local_target="no divergence — all target nodes already on-target",
            ),
            source=None,
        )

    # Step 2 — replay + state at X.
    steps = {s.ig_idx: s for s in replay_decisions(views)}
    step = steps[point.ig_idx]
    interferers = views_by_ig[point.ig_idx].interferers

    # Fail closed when the divergence can't be trusted.
    abstain_reasons = []
    if step.cap_hit:
        abstain_reasons.append("interferer row truncated (regenerate with an uncapped dump)")
    if step.unreliable:
        abstain_reasons.append("decision table incomplete (a missing node holds a callee-save)")
    if point.baseline_reg == 0 or point.target_reg == 0:
        abstain_reasons.append("divergence involves r0, a model boundary the replay cannot predict")
    if abstain_reasons:
        return FirstDivergenceReport(
            fact=AllocatorFact(
                class_id=target.class_id, ig_idx=point.ig_idx,
                case=DivergenceCase.ABSTAINED, iter_idx=point.iter_idx,
                baseline_reg=point.baseline_reg, target_reg=point.target_reg,
                coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
                blocker_ig=None, blocker_dependency=False,
                working_mask=step.working_mask, cap_hit=step.cap_hit,
                earlier_unmapped_warning=False,
                local_target="ABSTAINED — " + "; ".join(abstain_reasons),
            ),
            source=None,
        )

    fact = classify_divergence(point, step, target, views_by_ig, interferers)

    # Partial-map caveat: warn if an earlier non-target node exists.
    earlier_unmapped = any(
        v.ig_idx not in target.force_phys and v.iter_idx < point.iter_idx
        for v in views if v.ig_idx >= 0
    )
    if earlier_unmapped:
        fact = replace(fact, earlier_unmapped_warning=True)
    return FirstDivergenceReport(fact=fact, source=None)


_CONFIDENCE_RANK = {
    "verified": 0, "best-guess": 1, "low-confidence": 2,
    "ambiguous": 3, "ambiguous-nested": 4, "unsupported": 5, "rejected": 6,
}


def _list_bindings_safe(source_text: str, fn_name: str, pre_pass) -> list:
    """Best-effort symbol-bridge call; never raises (advisory layer). Returns []
    when there's nothing to map against (no source text or no pre-coloring pass)
    or on any bridge error. `symbol_bridge.list_bindings` takes
    (source, fn_name, pre_pass) — the fn_name must be the function NAME string and
    pre_pass a parser.Function pre-coloring pass."""
    if not source_text or pre_pass is None:
        return []
    try:
        from .symbol_bridge import list_bindings
        return list_bindings(source_text, fn_name, pre_pass)
    except Exception:
        return []


def _binding_is_inverse_actionable(binding) -> bool:
    return getattr(binding, "confidence", "") != "ambiguous-nested"


def _binding_label(binding) -> str:
    name = getattr(binding, "var_name", "?")
    confidence = getattr(binding, "confidence", "")
    scope = "/".join(getattr(binding, "scope_path", ()) or ())
    suffix = f" [{confidence}]" if confidence else ""
    if scope:
        suffix += f" scope={scope}"
    return f"{name}{suffix}"


def _first_def_summary(ig_idx: int, pre_pass) -> Optional[str]:
    if pre_pass is None:
        return None
    try:
        from .symbol_bridge import find_first_def
        first = find_first_def(ig_idx, pre_pass)
    except Exception:
        return None
    if first is None:
        return None
    return f"B{first.block_idx}: {first.opcode} {first.operands}"


def _source_context_for_ig(
    ig_idx: int,
    bindings: list,
    pre_pass,
) -> tuple[Optional[object], tuple[str, ...], tuple[str, ...], Optional[str]]:
    matches = [
        b for b in bindings
        if getattr(b, "virtual", -1) == ig_idx
    ]
    matches.sort(key=lambda b: (_CONFIDENCE_RANK.get(getattr(b, "confidence", ""), 9),
                                len(getattr(b, "scope_path", ()))))
    actionable = [b for b in matches if _binding_is_inverse_actionable(b)]
    rejected = tuple(
        _binding_label(b) for b in matches
        if not _binding_is_inverse_actionable(b)
    )
    best = actionable[0] if actionable else None
    alternates = tuple(getattr(b, "var_name", "?") for b in actionable[1:])
    first_def = None if best is not None else _first_def_summary(ig_idx, pre_pass)
    return best, alternates, rejected, first_def


def attach_source_ideas(fact: AllocatorFact, source_text: str, fn_name: str,
                        pre_pass) -> SourceIdea:
    """Step 4/5 advisory layer (NEVER gated). Emits the ig->var best guess +
    confidence-ranked alternates, plus case-level structural ideas. The
    structural ideas are always present; the var binding degrades to None when
    the bridge can't resolve one (no source/pre-pass, or a compiler temp)."""
    all_bindings = _list_bindings_safe(source_text, fn_name, pre_pass)
    best, alternates, rejected, first_def = _source_context_for_ig(
        fact.ig_idx, all_bindings, pre_pass
    )
    blocker_best = None
    blocker_alternates: tuple[str, ...] = ()
    blocker_rejected: tuple[str, ...] = ()
    blocker_first_def: Optional[str] = None
    if fact.blocker_ig is not None:
        (
            blocker_best,
            blocker_alternates,
            blocker_rejected,
            blocker_first_def,
        ) = _source_context_for_ig(fact.blocker_ig, all_bindings, pre_pass)

    ideas: list[str] = [fact.local_target]
    if fact.case is DivergenceCase.A_BLOCKED and best is not None:
        ideas.append(f"shorten {best.var_name}'s live range so it doesn't overlap the blocker")
    if fact.case is DivergenceCase.A_BLOCKED and blocker_best is not None:
        ideas.append(
            f"shorten or split blocker {blocker_best.var_name}'s live range "
            "so the target register is free"
        )
    elif fact.case is DivergenceCase.A_BLOCKED and blocker_first_def is not None:
        ideas.append(
            f"trace blocker ig {fact.blocker_ig}'s first def "
            f"({blocker_first_def}) and shorten that source expression"
        )
    if fact.case is DivergenceCase.D_COALESCED and best is not None:
        ideas.append(f"split {best.var_name} so MWCC can't merge it into its coalesce root")

    return SourceIdea(
        ig_idx=fact.ig_idx,
        var_name=(best.var_name if best is not None else None),
        confidence=(best.confidence if best is not None else None),
        alternates=alternates,
        ideas=tuple(ideas),
        rejected=rejected,
        first_def=first_def,
        blocker_ig=fact.blocker_ig,
        blocker_var_name=(
            blocker_best.var_name if blocker_best is not None else None
        ),
        blocker_confidence=(
            blocker_best.confidence if blocker_best is not None else None
        ),
        blocker_alternates=blocker_alternates,
        blocker_rejected=blocker_rejected,
        blocker_first_def=blocker_first_def,
    )


def replay_decisions(views) -> list[ReplayStep]:
    """Step 2. Replay decisions in recorded iter order, reconstructing the working
    mask at each. Pool is sticky: dispensed callee-saves are returned to the
    volatile pool for later reuse (lowest-set-bit can then pick them).

    NOTE (r0 boundary): r0 is excluded from `working` and from dispense, so
    `predicted_reg` is never 0. MWCC does assign r0 to some short-lived/degree-0
    virtuals, which this model cannot predict (same limitation as the forward
    simulator). Consumers treat a recorded r0 as a model boundary (Check 1 skips
    recorded-r0 decisions; the analyze pipeline abstains on r0 divergences),
    not as a genuine mismatch.
    """
    ordered = sorted(views, key=lambda d: d.iter_idx)
    iter_by_ig = {v.ig_idx: v.iter_idx for v in ordered if v.ig_idx >= 0}
    pool = set(INITIAL_VOLATILE_REGS)
    steps: list[ReplayStep] = []

    for v in ordered:
        fixed_blockers: set[int] = set()
        processed_blockers: set[int] = set()
        unreliable = False
        for (i_ig, i_reg) in v.interferers:
            if i_ig in iter_by_ig:
                if iter_by_ig[i_ig] < v.iter_idx and 0 <= i_reg <= 31:
                    processed_blockers.add(i_reg)   # already colored -> blocks
                # future virtual (iter >= current) -> not assigned yet -> no block
            else:
                # interferer has no decision row of its own
                if 0 <= i_reg <= 12:
                    fixed_blockers.add(i_reg)        # genuine precolored physical
                elif 13 <= i_reg <= 31:
                    # callee-save held by a node missing from the decision table
                    # => the table is incomplete; record it but mark the step
                    # unreliable so consumers fail closed instead of trusting an
                    # over-constrained mask.
                    fixed_blockers.add(i_reg)
                    unreliable = True
                # else (i_reg < 0 or > 31): placeholder / virtual leak -> ignore
        blockers = processed_blockers | fixed_blockers
        working = (pool - blockers) - RESERVED_REGS - {0}

        if working:
            predicted = min(working)                 # lowest set bit
            dispensed = False
        else:
            predicted = -1
            dispensed = True
            for r in NONVOLATILE_ALLOC_ORDER:        # top-down r31..r13
                if r not in pool and r not in blockers:
                    predicted = r
                    pool.add(r)                      # sticky: returns to pool
                    break

        steps.append(ReplayStep(
            ig_idx=v.ig_idx, iter_idx=v.iter_idx,
            working_mask=frozenset(working), predicted_reg=predicted,
            dispensed=dispensed, cap_hit=is_cap_hit(v),
            blockers=frozenset(blockers), unreliable=unreliable,
        ))
    return steps


def parse_force_phys_arg(raw: str) -> dict[int, int]:
    """Parse 'ig:phys[,ig:phys]*' (class prefixes like 'gpr:ig:phys' are accepted
    and the class is dropped — v1 operates within a single --class)."""
    out: dict[int, int] = {}
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        parts = entry.split(":")
        if len(parts) == 3:
            parts = parts[1:]            # drop class prefix
        if len(parts) != 2:
            raise ValueError(f"bad force-phys entry: {entry!r}")
        out[int(parts[0])] = int(parts[1])
    return out


def format_report(report: FirstDivergenceReport) -> str:
    f = report.fact
    lines = ["=== ALLOCATOR FACTS (gated) ==="]
    if f.case is DivergenceCase.D_COALESCED:
        nodes = ", ".join(str(n) for n in f.coalesced_nodes)
        lines.append(f"First divergence: class {f.class_id}, Case D — "
                     f"node(s) {nodes} coalesced into root {f.coalesced_root} "
                     f"[r{f.coalesced_root_phys}]")
    elif f.case in (DivergenceCase.NONE, DivergenceCase.ABSTAINED):
        lines.append(f"class {f.class_id}: {f.local_target}")
    else:
        lines.append(f"First divergence: class {f.class_id}, iter {f.iter_idx}, "
                     f"ig_idx {f.ig_idx}")
        lines.append(f"  baseline: ig {f.ig_idx} -> r{f.baseline_reg}")
        lines.append(f"  target:   ig {f.ig_idx} -> r{f.target_reg}")
        lines.append(f"  cause: Case {f.case.value}"
                     + (f" — r{f.target_reg} held by interferer ig {f.blocker_ig}"
                        if f.case is DivergenceCase.A_BLOCKED else ""))
    lines.append(f"  local target: {f.local_target}")
    if f.cap_hit:
        lines.append("  WARNING: interferer row truncated — abstained (regenerate uncapped dump)")
    if f.earlier_unmapped_warning:
        lines.append("  NOTE: partial target map — an earlier unmapped node may dominate")

    lines.append("")
    lines.append("=== SOURCE IDEAS (ADVISORY, not validated) ===")
    s = report.source
    if s is None:
        lines.append("  (run with --source to attach symbol-bridge ideas)")
    else:
        if s.var_name is None:
            lines.append(f"  ig {s.ig_idx} -> (no source variable bound — "
                         f"likely a compiler temp / coalesced / spill node)")
            if s.first_def:
                lines.append(f"    first def: {s.first_def}")
        else:
            lines.append(f"  ig {s.ig_idx} -> var {s.var_name} [confidence: {s.confidence}]")
        if s.alternates:
            lines.append(f"  alternates: {', '.join(s.alternates)}")
        if s.rejected:
            lines.append(
                "  rejected candidates: "
                + "; ".join(s.rejected)
                + " (nested lexical scope not validated for this live range)"
            )
        if s.blocker_ig is not None:
            lines.append("")
            lines.append(f"  blocker ig {s.blocker_ig}:")
            if s.blocker_var_name is None:
                lines.append("    no source variable bound")
                if s.blocker_first_def:
                    lines.append(f"    first def: {s.blocker_first_def}")
            else:
                lines.append(
                    f"    var {s.blocker_var_name} "
                    f"[confidence: {s.blocker_confidence}]"
                )
            if s.blocker_alternates:
                lines.append(
                    f"    alternates: {', '.join(s.blocker_alternates)}"
                )
            if s.blocker_rejected:
                lines.append(
                    "    rejected candidates: "
                    + "; ".join(s.blocker_rejected)
                    + " (nested lexical scope not validated for this live range)"
                )
        for i, idea in enumerate(s.ideas, 1):
            lines.append(f"    {i}. {idea}")
    return "\n".join(lines)
