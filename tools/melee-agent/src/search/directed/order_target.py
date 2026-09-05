"""OrderTarget — the persisted, human-auditable per-function order-distance
target artifact (§4.3 of the order-distance directed-search spec).

An OrderTarget records, for one pool function:
  * the PHYS assignment evidence (force-phys-from-diff) — NOT the order source;
  * the TRUE order forcing list (--force-iter-first), <= 64 entries, where the
    ig at 0-based list index i lands at DECISIONS rank i+1 (verified semantics:
    the 9ACC live test in tests/search/directed/test_order_metric.py);
  * the PROVEN order vector read back from the FORCED build's COLORGRAPH
    DECISIONS (the anti-hollowness source);
  * the pruned target-role set + the honestly-unscored residual;
  * the recorded named pair for the kill-switch assertion (c), with provenance;
  * derive-twice determinism evidence; and
  * the routing classification (the class partition).

This module is pure data: schema dataclass, the Routing enum, YAML load/save,
and validation. Derivation (which fills it in) lives in
src.mwcc_debug.order_target_derive (Plan A T3).
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class Routing(enum.Enum):
    """The class partition: every derivation outcome is one of these."""

    DIRECTED = "directed"               # forced-ORDER build eliminates the class residual
    NOT_ORDER_CLASS = "not_order_class"  # order is a symptom (instruction-content/emission/coalescing/VN/liveness root)
    UNANCHORABLE = "unanchorable"        # <2 roles survive baseline self-reanchor
    FORCE_CAP_BLOCKED = "force_cap_blocked"  # no <=64-entry forcing set eliminates residual
    UNSTABLE_TARGET = "unstable_target"  # force misapplied / ig-set drift / derive-twice mismatch


# Exit codes mirror routing (§5.2); 0 == directed.
ROUTING_EXIT_CODES: dict[str, int] = {
    Routing.DIRECTED.value: 0,
    Routing.UNANCHORABLE.value: 3,
    Routing.NOT_ORDER_CLASS.value: 4,
    Routing.FORCE_CAP_BLOCKED.value: 5,
    Routing.UNSTABLE_TARGET.value: 6,
}

FORCE_CAP = 64  # the DLL override parser caps at 64 entries and silently no-ops beyond.


class ValidationError(Exception):
    """Raised when an OrderTarget violates a structural invariant."""


@dataclass
class OrderTarget:
    """Persisted order-distance target. Field order/names mirror spec §4.3,
    plus the kill-switch named-pair fields (B7)."""

    function: str
    unit: str
    class_id: int
    # Step 2 — assignment evidence (NOT the order source):
    phys_target: dict           # {orig_ig: desired_phys}
    phys_conflicts: list        # non-empty => not_order_class
    # Step 3 — the TRUE order forcing (provenance):
    force_iter_first: list      # the chosen verified forcing list (<= 64)
    # Step 5 — the PROVEN vector, read back from the FORCED build's DECISIONS:
    order_target: dict          # {orig_ig: rank in the forced build}
    # Step 6 — identity:
    target_roles: list          # pruned, baseline-self-reanchor-confident
    unscored_roles: list        # [{ig, reason}] — honest unscored residual
    # Step 7 — determinism evidence:
    forced_decisions_sha256: list  # two independent forced readbacks, must match
    baseline_source_sha256: str
    baseline_pcdump_sha256: str
    # Routing (the class partition):
    routing: str                # one of Routing values
    class_evidence: str = ""
    # Optional diagnostic from the collector's bounded force-vector verifier.
    # Present mainly on not_order_class/inconclusive routings so callers can
    # see exactly which force vector was tried and whether it timed out.
    force_vector_probe: dict | None = None
    # Kill-switch assertion (c): the recorded pair that must flip, + provenance.
    named_pair: list = field(default_factory=list)
    named_pair_provenance: str = ""

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def save_yaml(self, path: Any) -> None:
        import yaml
        Path(path).write_text(
            yaml.safe_dump(asdict(self), sort_keys=False), encoding="utf-8"
        )

    @classmethod
    def load_yaml(cls, path: Any) -> "OrderTarget":
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        # YAML stringifies non-string dict keys on dump; coerce the two ig-keyed
        # maps back to int keys so downstream consumers see {int: int}.
        data["phys_target"] = {int(k): int(v) for k, v in (data.get("phys_target") or {}).items()}
        data["order_target"] = {int(k): int(v) for k, v in (data.get("order_target") or {}).items()}
        return cls(**data)

    def exit_code(self) -> int:
        return ROUTING_EXIT_CODES.get(self.routing, 1)


def validate_order_target(t: OrderTarget) -> None:
    """Raise ValidationError if *t* violates a structural invariant.

    Non-directed routings skip the directed-only invariants (they intentionally
    carry empty roles / conflict evidence). A directed target must be loop-ready.
    """
    valid_routings = {r.value for r in Routing}
    if t.routing not in valid_routings:
        raise ValidationError(
            f"unknown routing {t.routing!r}; expected one of {sorted(valid_routings)}"
        )
    if len(t.force_iter_first) > FORCE_CAP:
        raise ValidationError(
            f"force_iter_first has {len(t.force_iter_first)} entries; the DLL cap is {FORCE_CAP}"
        )
    if t.routing != Routing.DIRECTED.value:
        return
    # Directed-only invariants:
    if t.phys_conflicts:
        raise ValidationError(
            "routing=directed but phys_conflicts is non-empty (should be not_order_class)"
        )
    if len(t.target_roles) < 2:
        raise ValidationError(
            f"routing=directed needs at least 2 target_roles; got {len(t.target_roles)}"
        )
    missing = [r for r in t.target_roles if r not in t.order_target]
    if missing:
        raise ValidationError(
            f"target_roles {missing} not present in order_target keys"
        )
    if t.named_pair:
        if len(t.named_pair) != 2 or any(ig not in t.target_roles for ig in t.named_pair):
            raise ValidationError(
                f"named_pair {t.named_pair} must be exactly 2 igs drawn from "
                f"target_roles {t.target_roles}"
            )
