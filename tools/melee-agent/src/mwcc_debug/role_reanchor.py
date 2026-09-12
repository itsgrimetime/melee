from __future__ import annotations
from dataclasses import dataclass, field
from . import role_matcher as rm
from . import role_descriptor as rd


@dataclass(frozen=True)
class ReanchorResult:
    class_id: int
    force_phys: dict          # new_ig -> desired_phys (matched + round-trip-confirmed only)
    diagnostics: dict         # original_ig -> status string (everything excluded from the map)
    matched: dict = field(default_factory=dict)   # new_ig -> original_ig (round-trip-confirmed)


def _confirm_round_trip(forward: dict, inverse: dict, desired: dict):
    """Keep a forward MATCHED role only if the new node maps back to it.
    forward: orig_ig -> RoleMatch (target->new); inverse: new_ig -> RoleMatch
    (new->target). Returns (force_phys{new_ig: phys}, diagnostics{orig_ig: status},
    matched{new_ig: orig_ig})."""
    force_phys, diagnostics, matched = {}, {}, {}
    for orig_ig, m in forward.items():
        if m.status != rm.MatchStatus.MATCHED:
            diagnostics[orig_ig] = m.status.value
            continue
        if orig_ig not in desired:            # public seam: ref superset of desired
            diagnostics[orig_ig] = "no_desired_phys"
            continue
        inv = inverse.get(m.new_ig)
        if inv is not None and inv.status == rm.MatchStatus.MATCHED and inv.new_ig == orig_ig:
            force_phys[m.new_ig] = desired[orig_ig]
            matched[m.new_ig] = orig_ig
        else:
            diagnostics[orig_ig] = "unstable_identity"   # forward-only, not invertible
    return force_phys, diagnostics, matched


def reanchor_descs(ref: dict, cand: dict, desired: dict, class_id: int = 0,
                   pre_diag=None) -> ReanchorResult:
    forward = rm.match_roles(ref, cand) if ref else {}
    inverse = rm.match_roles(cand, ref) if (cand and ref) else {}
    force_phys, diagnostics, matched = _confirm_round_trip(forward, inverse, desired)
    if pre_diag:
        diagnostics = {**pre_diag, **diagnostics}
    return ReanchorResult(class_id=class_id, force_phys=force_phys,
                          diagnostics=diagnostics, matched=matched)


def reanchor_to_target_spec(res: ReanchorResult, function: str, spilled: list | None = None) -> dict:
    """The {function, virtuals, spilled} dict that `first-divergence` consumes
    (same shape as `target derive --force-phys-safe`)."""
    return {"function": function, "virtuals": dict(res.force_phys),
            "spilled": sorted(spilled or [])}


def reanchor(target: "rd.TargetSpec", new_compile: "rd.Compile", class_id: int = 0) -> ReanchorResult:
    """Map a fixed TargetSpec into new_compile's ig-numbering via the matcher.
    Uses forward + inverse round-trip confirmation: only roles that map forward
    AND have the new node map back (MATCHED, same orig_ig) become force-phys
    entries. Roles without a descriptor (structural Case D/E), non-matched, or
    not round-trip-stable are routed to diagnostics and excluded from the map."""
    cand = rd.build_descriptors(new_compile, class_id)
    roles = [r for r in target.roles if r.class_id == class_id]
    desired = {r.original_ig: r.desired_phys for r in roles}
    ref = {r.original_ig: r.descriptor for r in roles if r.descriptor is not None}
    pre_diag = {r.original_ig: "no_descriptor" for r in roles if r.descriptor is None}
    return reanchor_descs(ref, cand, desired, class_id, pre_diag=pre_diag)
