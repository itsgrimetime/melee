# Order-Distance Directed Search — Plans A+B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the order-distance objective core (a proven per-function `OrderTarget` artifact + a derivation/classification CLI + an order-mode scoring path) and a frozen-fixture kill-switch experiment that decides — before any pool campaign — whether the metric retrodicts the known `mnDiagram_802427B4` win.

**Architecture:** This is wiring + data + validation between pieces that already exist (the role-anchored identity layer in `mwcc_debug/`, the Kendall `order_distance` metric, the `force-phys-from-diff` / `match-iter-first` / `dump local --force-iter-first` diagnostic tools, and the directed scorer). Plan A adds a persisted `OrderTarget` YAML schema, a `debug target order-target` derivation pipeline that turns each derivation *outcome* into a named routing classification, an order-mode branch in the scorer that exposes the order objective with hardened §3.3 coverage validity (without touching gate/scheduler polarity — that is Plan C), and a generalized reanchored scoring core shared by the scorer and the kill-switch. Plan B freezes the pre-win / win / negative-control fixtures from commit `a527c0227` and its parent, derives an `OrderTarget` on the pre-win base (with an explicit eligibility contingency and the cardstate decl-chain fallback), and runs four assertions that fire a STOP if the metric cannot retrodict the win.

**Tech Stack:** Python 3.11, `typer` (CLI), `pyyaml` (artifact persistence — a hard project dependency), `pytest` (`--no-cov` for focused runs), the existing `src.mwcc_debug` role layer and `src.search.directed` scorer.

---

## Conventions for every task in this plan

- **Worktree (pin all commands here):** `/Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign`. Do NOT `cd /Users/mike/code/melee` — that builds the shared main checkout.
- **Test working directory:** `tools/melee-agent`. All `pytest` / `python -m` commands run from there. Because steps cannot persist `cd`, every command is written as a single `cd <worktree>/tools/melee-agent && <cmd>` line.
- **Focused test runs use `--no-cov`** — the repo's default `addopts` enables coverage, which floods output. Example: `python -m pytest tests/search/directed/test_order_target.py -q --no-cov`.
- **All new CLI lands in the PACKAGE copies only:** `tools/melee-agent/src/search/cli/__init__.py` and `tools/melee-agent/src/cli/debug/__init__.py`. NEVER edit the legacy ~1MB siblings `tools/melee-agent/src/search/cli.py` or `tools/melee-agent/src/cli/debug.py` (issue #583 — duplication is filed; new code must not feed it).
- **Plans A+B do NOT touch `gate.py` or `scheduler.py`.** Their higher-is-better polarity is Plan C (T8/T9). The kill-switch (T7) reads order scores directly from the generalized scoring core (T5), never through the gate.
- **Imports inside `src/` use the `src.` package root** (e.g. `from src.search.directed.order_target import OrderTarget`), matching every existing module.

---

## File Structure

New files:
- `tools/melee-agent/src/search/directed/order_target.py` — the `OrderTarget` dataclass, the `Routing` enum, YAML load/save, and validation. (T2)
- `tools/melee-agent/tests/search/directed/test_order_target.py` — unit tests for T2.
- `tools/melee-agent/src/mwcc_debug/order_target_derive.py` — the pure derivation/classification helper (`derive_order_target`) that the CLI wraps; takes injectable tool callables so it is unit-testable without mwcc. (T3)
- `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py` — unit tests for the derivation classifier (T3).
- `tools/melee-agent/tests/cli/test_order_target_cli.py` — CLI wiring + exit-code tests for `debug target order-target` (T3).
- `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/` — frozen fixtures: `pre_win.c`, `win.c`, `negative_control.c`, `*.pcdump.txt`, `order_target.yaml`, `PROVENANCE.md`. (T6)
- `tools/melee-agent/tests/search/directed/test_kill_switch.py` — the kill-switch harness + assertions (a)-(d) + the cardstate secondary witness. (T7)
- `tools/melee-agent/src/search/directed/kill_switch.py` — the harness function the test (and a future CLI) call. (T7)
- `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md` — the result/refutation doc written by T7's run. (T7)

Modified files:
- `tools/melee-agent/src/search/directed/contracts.py:9` — add `objective_mode` + OrderTarget-sourced fields to `DirectedObjective`. (T1)
- `tools/melee-agent/src/search/directed/order_metric.py:204` — generalize `CandidateScore` + `score_candidate_reanchored` to an arbitrary role set; add the §3.3 coverage validity. (T5)
- `tools/melee-agent/src/search/directed/scorer.py:143` — add the `objective_mode == "order"` branch to `score_directed`. (T4)
- `tools/melee-agent/src/cli/debug/__init__.py` — register `@target_app.command("order-target")`. (T3)

---

## Plan A — objective core

### Task 1: `objective_mode` + OrderTarget-sourced fields on `DirectedObjective`

The frozen `DirectedObjective` dataclass (`contracts.py:9`) has no `objective_mode` field today; the scorer hardcodes phys-match. Add the field (default `"phys"` for backward compatibility) plus the two OrderTarget-sourced fields the order branch and CLI will populate. New dataclass fields with defaults are append-only, so every existing positional construction site (`objective.py`, `run.py`, `test_scorer.py`) keeps working unchanged.

**Files:**
- Modify: `tools/melee-agent/src/search/directed/contracts.py:9-21`
- Test: `tools/melee-agent/tests/search/directed/test_contracts.py`

- [ ] **Step 1: Write the failing test**

Append to `tools/melee-agent/tests/search/directed/test_contracts.py`:

```python
def test_directed_objective_defaults_to_phys_mode():
    from src.search.directed.contracts import DirectedObjective
    obj = DirectedObjective(
        search_target=None, role_target=None, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={}, proof_force_phys={},
    )
    assert obj.objective_mode == "phys"
    assert obj.order_target_roles == ()
    assert obj.unscored_roles == ()


def test_directed_objective_accepts_order_mode():
    from src.search.directed.contracts import DirectedObjective
    obj = DirectedObjective(
        search_target=None, role_target=None, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig={28: 4, 29: 6}, proof_force_phys={28: 29, 29: 28},
        objective_mode="order", order_target_roles=(28, 29),
        unscored_roles=({"ig": 31, "reason": "ambiguous_signature"},),
    )
    assert obj.objective_mode == "order"
    assert obj.order_target_roles == (28, 29)
    assert obj.unscored_roles[0]["ig"] == 31
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_contracts.py -q --no-cov -k objective_mode`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'objective_mode'`.

- [ ] **Step 3: Add the fields**

In `tools/melee-agent/src/search/directed/contracts.py`, replace the `DirectedObjective` class body (lines 9-21) with:

```python
@dataclass(frozen=True)
class DirectedObjective:
    """Specifies what the directed search is trying to achieve."""

    search_target: Any  # TargetSpec | None
    role_target: Any  # role descriptor | None
    baseline_compile: Any  # CompileSpec | None
    baseline_pcdump_path: Any  # Path | None
    baseline_source_hash: str
    class_id: int
    objective_iter_by_original_ig: dict
    proof_force_phys: dict
    # --- ORDER-DISTANCE OBJECTIVE (order-distance directed search, Plan A T1) ---
    # objective_mode selects the scorer branch: "phys" (default, the shipped
    # phys-match gate signal) or "order" (Kendall vs a forced-ORDER-proven
    # target vector, exposed for the kill switch + the future order loop).
    # objective_iter_by_original_ig carries the PROVEN order vector when
    # objective_mode == "order" (sourced from OrderTarget.order_target).
    # order_target_roles is the pruned, baseline-self-reanchor-confident
    # target-role set (§3.3); unscored_roles records honestly-unscored residual.
    objective_mode: str = "phys"
    order_target_roles: tuple = ()
    unscored_roles: tuple = ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_contracts.py -q --no-cov`
Expected: PASS (all existing contract tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/contracts.py tools/melee-agent/tests/search/directed/test_contracts.py && git commit -m "feat(directed): objective_mode + OrderTarget fields on DirectedObjective (T1)"
```

---

### Task 2: `OrderTarget` artifact module

A small, persisted, human-auditable YAML artifact (§4.3) plus the routing enum and a validation function. This is pure data plumbing — no mwcc. The schema mirrors §4.3 exactly. Validation enforces the structural invariants the derivation pipeline (T3) and the kill switch (T7) rely on: routing is one of the five enum values; when `routing == "directed"` there must be ≥2 `target_roles`, `phys_conflicts` must be empty, every `target_role` must appear in `order_target`, and `force_iter_first` must be ≤64 entries.

**Files:**
- Create: `tools/melee-agent/src/search/directed/order_target.py`
- Test: `tools/melee-agent/tests/search/directed/test_order_target.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/directed/test_order_target.py`:

```python
import pytest

from src.search.directed.order_target import (
    OrderTarget,
    Routing,
    ValidationError,
    validate_order_target,
)


def _directed_target(**over):
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        force_iter_first=[46, 28, 29],
        order_target={28: 5, 29: 7},
        target_roles=[28, 29],
        unscored_roles=[],
        forced_decisions_sha256=["aa", "aa"],
        baseline_source_sha256="bb",
        baseline_pcdump_sha256="cc",
        routing="directed",
        class_evidence="",
    )
    base.update(over)
    return OrderTarget(**base)


def test_routing_enum_values():
    assert {r.value for r in Routing} == {
        "directed", "not_order_class", "unanchorable",
        "force_cap_blocked", "unstable_target",
    }


def test_roundtrip_yaml(tmp_path):
    t = _directed_target()
    path = tmp_path / "mnDiagram_OnFrame.yaml"
    t.save_yaml(path)
    loaded = OrderTarget.load_yaml(path)
    assert loaded == t
    # int keys must survive the YAML round-trip (YAML stringifies dict keys).
    assert loaded.order_target == {28: 5, 29: 7}
    assert loaded.phys_target == {28: 29, 29: 28}


def test_validate_directed_ok():
    validate_order_target(_directed_target())  # no raise


def test_validate_directed_requires_two_roles():
    with pytest.raises(ValidationError, match="at least 2 target_roles"):
        validate_order_target(_directed_target(target_roles=[28], order_target={28: 5}))


def test_validate_directed_rejects_conflicts():
    with pytest.raises(ValidationError, match="phys_conflicts"):
        validate_order_target(_directed_target(
            phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))


def test_validate_directed_target_role_must_be_in_order_target():
    with pytest.raises(ValidationError, match="not present in order_target"):
        validate_order_target(_directed_target(target_roles=[28, 99]))


def test_validate_force_cap():
    with pytest.raises(ValidationError, match="64"):
        validate_order_target(_directed_target(force_iter_first=list(range(65))))


def test_validate_non_directed_skips_role_checks():
    # A not_order_class target need not satisfy the directed invariants.
    t = _directed_target(
        routing="not_order_class", target_roles=[], order_target={},
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}],
        class_evidence=(
            "instruction-content/emission divergence upstream of select "
            "(8024227C: param-alias statement-copy skew; ORACLE ROUND 2 erratum, "
            "commit 8bd6f8648 — the round-1 ig56 arg-home-coalesce attribution "
            "was a match-iter-first [ambiguous] artifact)"
        ),
    )
    validate_order_target(t)  # no raise


def test_validate_unknown_routing():
    with pytest.raises(ValidationError, match="routing"):
        validate_order_target(_directed_target(routing="bogus"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_target.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.search.directed.order_target'`.

- [ ] **Step 3: Implement the module**

Create `tools/melee-agent/src/search/directed/order_target.py`:

```python
"""OrderTarget — the persisted, human-auditable per-function order-distance
target artifact (§4.3 of the order-distance directed-search spec).

An OrderTarget records, for one pool function:
  * the PHYS assignment evidence (force-phys-from-diff) — NOT the order source;
  * the TRUE order forcing list (--force-iter-first), <= 64 entries;
  * the PROVEN order vector read back from the FORCED build's COLORGRAPH
    DECISIONS (the anti-hollowness source);
  * the pruned target-role set + the honestly-unscored residual;
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
    UNSTABLE_TARGET = "unstable_target"  # derive-twice mismatch (nondeterministic forced build)


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
    """Persisted order-distance target. Field order/names mirror spec §4.3."""

    function: str
    unit: str
    class_id: int
    # Step 2 — assignment evidence (NOT the order source):
    phys_target: dict           # {orig_ig: desired_phys}
    phys_conflicts: list        # non-empty => not_order_class
    # Step 3 — the TRUE order forcing (provenance):
    force_iter_first: list      # the minimal verified forcing list (<= 64)
    # Step 5 — the PROVEN vector, read from the FORCED build's DECISIONS:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_target.py -q --no-cov`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/order_target.py tools/melee-agent/tests/search/directed/test_order_target.py && git commit -m "feat(directed): OrderTarget artifact + Routing enum + validation (T2)"
```

---

### Task 3: Derivation pipeline `debug target order-target`

This is the largest task. It orchestrates four existing tools into the §4.2 pipeline and turns every failure mode into a named routing. To keep it testable without mwcc, the classification logic lives in a **pure helper** (`derive_order_target`) that takes the tool *outputs* (already-parsed dicts) plus injectable callables, and returns an `OrderTarget`. The CLI command is a thin wrapper that calls the real tools and prints/persists the result with routing-mirrored exit codes.

**Why routing keys on the forced-order byte-verdict, not on attribution (validation rationale):** the classifier's routing decision must depend ONLY on whether the forced-ORDER build byte-eliminates the class residual (steps 3-4), never on the *named cause* of a residual. The `8024227C` case proves this is the right contract: ORACLE ROUND 2 (commit `8bd6f8648`) retracted the round-1 root-cause attribution (it was a `match-iter-first [ambiguous]` artifact, not arg-home coalescing — the real root was a `void* gobj = arg0;` param-alias statement-copy emission skew), yet the `not_order_class` routing **stood unchanged** because the forced order still did not byte-match. The classifier was correct even though the first-round attribution was wrong — exactly the robustness property a partition needs. Hence `class_evidence` strings are framed as leads to confirm, not proofs.

The pipeline (§4.2), in order, each step a named classification on failure:
1. **Precondition:** register-only checkdiff (`tools/checkdiff.py <fn> --format json`, classification must be register-only / FULLNORM-0). A structural diff is not in this pool.
2. **Phys target + conflict classifier:** `force-phys-from-diff -f <fn> --verify --json` → `{orig_ig: phys}` + `conflicts`. **Any conflict entry ⟹ `not_order_class` immediately** (before spending a forced compile).
3. **TRUE forced-ORDER compile:** `match-iter-first -f <fn> --json` recommends the `--force-iter-first` ig list; if it exceeds 64 ⟹ `force_cap_blocked`. Run `dump local <tu> --force-iter-first <list> --force-iter-first-fn <fn> --diff` and **verify application** (every forced ig sits at its forced position in the forced DECISIONS readback) — a silently-unapplied force never produces a target.
4. **Class-partition gate:** the forced build must byte-eliminate the targeted class residual; if not ⟹ `not_order_class`.
5. **Readback:** `colorgraph_ranks` of the FORCED build → `order_target`; assert forced ig-set ≡ baseline ig-set.
6. **Target-role pruning (§3.3):** keep only roles that round-trip MATCHED on baseline self-reanchor; record failures in `unscored_roles`. <2 survivors ⟹ `unanchorable`.
7. **Determinism (derive twice):** a second forced compile + readback; mismatched DECISIONS-section hash ⟹ `unstable_target`.
8. **Persist** the `OrderTarget`.

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/order_target_derive.py`
- Create: `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py` (register `@target_app.command("order-target")`)
- Create: `tools/melee-agent/tests/cli/test_order_target_cli.py`

- [ ] **Step 1: Write the failing tests for the pure classifier**

Create `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py`:

```python
import pytest

from src.mwcc_debug.order_target_derive import derive_order_target, DeriveInputs
from src.search.directed.order_target import Routing


def _inputs(**over):
    """Build a DeriveInputs whose default tool outputs describe a clean,
    directed, two-role function (mnDiagram_OnFrame-shaped)."""
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        # Step 1: register-only checkdiff.
        checkdiff_classification="register",
        # Step 2: force-phys-from-diff.
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        # Step 3: match-iter-first recommended list.
        force_iter_first=[46, 28, 29],
        # Step 3 verify-application: each forced ig -> the rank it landed at.
        applied_positions={46: 0, 28: 4, 29: 6},
        # Step 4: forced build eliminated the class residual.
        forced_class_clean=True,
        # Step 5: the forced build's COLORGRAPH ranks {ig: rank}.
        forced_ranks={46: 1, 28: 5, 29: 7},
        baseline_ig_set={46, 28, 29, 31},
        forced_ig_set={46, 28, 29, 31},
        # Step 6: roles that self-reanchor MATCHED on the baseline.
        self_reanchored_roles={28, 29},
        unscored_roles=[{"ig": 31, "reason": "ambiguous_signature"}],
        # Step 7: two forced DECISIONS-section hashes.
        forced_decisions_sha256=["hashA", "hashA"],
        baseline_source_sha256="src1",
        baseline_pcdump_sha256="pc1",
    )
    base.update(over)
    return DeriveInputs(**base)


def test_clean_two_role_routes_directed():
    t = derive_order_target(_inputs())
    assert t.routing == Routing.DIRECTED.value
    assert t.target_roles == [28, 29]
    assert t.order_target == {28: 5, 29: 7}
    assert t.exit_code() == 0


def test_structural_diff_aborts_before_pool():
    with pytest.raises(ValueError, match="register-only"):
        derive_order_target(_inputs(checkdiff_classification="structural"))


def test_phys_conflict_routes_not_order_class_early():
    t = derive_order_target(_inputs(
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))
    assert t.routing == Routing.NOT_ORDER_CLASS.value
    assert "ig56" in t.class_evidence or "56" in t.class_evidence
    assert t.exit_code() == 4


def test_force_cap_blocked_when_list_too_long():
    t = derive_order_target(_inputs(force_iter_first=list(range(65))))
    assert t.routing == Routing.FORCE_CAP_BLOCKED.value
    assert t.exit_code() == 5


def test_force_not_applied_routes_unstable_target():
    # ig29 was requested but landed nowhere (silent no-op) -> never a target.
    t = derive_order_target(_inputs(applied_positions={46: 0, 28: 4}))
    assert t.routing == Routing.UNSTABLE_TARGET.value
    assert t.exit_code() == 6


def test_class_residual_not_eliminated_routes_not_order_class():
    t = derive_order_target(_inputs(forced_class_clean=False))
    assert t.routing == Routing.NOT_ORDER_CLASS.value
    assert t.exit_code() == 4


def test_ig_set_drift_routes_unstable_target():
    t = derive_order_target(_inputs(forced_ig_set={46, 28, 29}))  # 31 vanished
    assert t.routing == Routing.UNSTABLE_TARGET.value


def test_fewer_than_two_roles_routes_unanchorable():
    t = derive_order_target(_inputs(self_reanchored_roles={28}))
    assert t.routing == Routing.UNANCHORABLE.value
    assert t.exit_code() == 3


def test_determinism_mismatch_routes_unstable_target():
    t = derive_order_target(_inputs(forced_decisions_sha256=["hashA", "hashB"]))
    assert t.routing == Routing.UNSTABLE_TARGET.value


def test_directed_target_validates():
    from src.search.directed.order_target import validate_order_target
    validate_order_target(derive_order_target(_inputs()))  # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/mwcc_debug/test_order_target_derive.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.mwcc_debug.order_target_derive'`.

- [ ] **Step 3: Implement the pure classifier**

Create `tools/melee-agent/src/mwcc_debug/order_target_derive.py`:

```python
"""derive_order_target — the §4.2 derivation/classification pipeline as a PURE
function over already-collected tool outputs.

The CLI (debug target order-target) collects the tool outputs (checkdiff,
force-phys-from-diff, match-iter-first, two forced dump readbacks, baseline
self-reanchor) and hands them here as a DeriveInputs. This function applies the
ordered classification (each failure mode is a named routing, never an error)
and returns an OrderTarget. Keeping it pure makes the partition logic unit-
testable without any mwcc compilation.

Ordering matters and matches §4.2:
  1. register-only precondition (a structural diff is NOT in this pool -> raise)
  2. phys conflict -> not_order_class (before any forced compile)
  3. force-list > 64 -> force_cap_blocked
  3v. forced ig not applied at its requested position -> unstable_target
  4. forced build did not eliminate the class residual -> not_order_class
  5. forced ig-set != baseline ig-set -> unstable_target
  6. < 2 self-reanchored roles -> unanchorable
  7. derive-twice DECISIONS hashes differ -> unstable_target
  else -> directed
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.search.directed.order_target import FORCE_CAP, OrderTarget, Routing


@dataclass
class DeriveInputs:
    """Collected tool outputs for one function's derivation."""

    function: str
    unit: str
    class_id: int
    checkdiff_classification: str          # "register" => FULLNORM-0
    phys_target: dict                      # {orig_ig: desired_phys}
    phys_conflicts: list                   # force-phys-from-diff conflicts
    force_iter_first: list                 # match-iter-first recommended list
    applied_positions: dict                # {forced_ig: rank it actually landed at}
    forced_class_clean: bool               # forced build byte-eliminated the class residual
    forced_ranks: dict                     # {ig: rank} from the FORCED COLORGRAPH DECISIONS
    baseline_ig_set: set
    forced_ig_set: set
    self_reanchored_roles: set             # baseline round-trip-MATCHED roles
    unscored_roles: list                   # [{ig, reason}]
    forced_decisions_sha256: list          # two independent forced readbacks
    baseline_source_sha256: str
    baseline_pcdump_sha256: str


def _target(inp: DeriveInputs, routing: Routing, *,
            target_roles: list | None = None,
            order_target: dict | None = None,
            class_evidence: str = "") -> OrderTarget:
    return OrderTarget(
        function=inp.function,
        unit=inp.unit,
        class_id=inp.class_id,
        phys_target=dict(inp.phys_target),
        phys_conflicts=list(inp.phys_conflicts),
        force_iter_first=list(inp.force_iter_first),
        order_target=dict(order_target or {}),
        target_roles=list(target_roles or []),
        unscored_roles=list(inp.unscored_roles),
        forced_decisions_sha256=list(inp.forced_decisions_sha256),
        baseline_source_sha256=inp.baseline_source_sha256,
        baseline_pcdump_sha256=inp.baseline_pcdump_sha256,
        routing=routing.value,
        class_evidence=class_evidence,
    )


def derive_order_target(inp: DeriveInputs) -> OrderTarget:
    # Step 1 — register-only precondition. A structural diff is not in this pool.
    if inp.checkdiff_classification != "register":
        raise ValueError(
            f"{inp.function}: checkdiff is {inp.checkdiff_classification!r}, "
            f"not register-only (FULLNORM-0); not in the order-distance pool"
        )

    # Step 2 — phys conflict classifier (BEFORE any forced compile).
    # A phys conflict (same virtual -> >=2 target physregs at different sites) is
    # a NODE-SET-divergence signal: the candidate causes are upstream of select
    # (instruction-content/emission skew, coalescing, VN, or liveness), not the
    # order. The forced-order byte-verdict (steps 3-4) is what the routing keys
    # on; the conflict's *attribution* is a lead to confirm, not a proof — cf.
    # 8024227C, whose round-1 "arg-home coalesce" attribution was a
    # match-iter-first [ambiguous] artifact (ORACLE ROUND 2 erratum, commit
    # 8bd6f8648) while the not_order_class routing nonetheless stood.
    if inp.phys_conflicts:
        igs = sorted({c.get("ig_idx") for c in inp.phys_conflicts if "ig_idx" in c})
        evidence = (
            "phys conflict ig" + ",ig".join(str(i) for i in igs)
            + ": same virtual wants multiple target physregs at different sites "
            "(node-set divergence upstream of select; confirm attribution)"
        ) if igs else (
            "phys conflict: same virtual wants multiple target physregs "
            "(node-set divergence upstream of select; confirm attribution)"
        )
        return _target(inp, Routing.NOT_ORDER_CLASS, class_evidence=evidence)

    # Step 3 — the 64-entry force cap (silent no-op beyond it).
    if len(inp.force_iter_first) > FORCE_CAP:
        return _target(
            inp, Routing.FORCE_CAP_BLOCKED,
            class_evidence=(
                f"no <= {FORCE_CAP}-entry forcing set: match-iter-first "
                f"recommended {len(inp.force_iter_first)} entries"
            ),
        )

    # Step 3 (verify application) — every forced ig must sit at its forced
    # position; a silently-unapplied force must never produce a target.
    unapplied = [ig for ig in inp.force_iter_first if ig not in inp.applied_positions]
    if unapplied:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            class_evidence=(
                f"forced igs {unapplied} did not apply in the forced DECISIONS "
                f"readback (silent no-op / stale DLL)"
            ),
        )

    # Step 4 — class-partition gate.
    if not inp.forced_class_clean:
        return _target(
            inp, Routing.NOT_ORDER_CLASS,
            class_evidence=(
                "forced-ORDER build did not byte-eliminate the class residual; "
                "order is a symptom of instruction-content/emission divergence "
                "upstream of select (e.g. coalescing/VN/liveness/statement-copy skew)"
            ),
        )

    # Step 5 — ig-set identity between baseline and forced build.
    if inp.baseline_ig_set != inp.forced_ig_set:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            class_evidence=(
                "forced-build ig-set != baseline ig-set: forcing perturbed IG "
                "construction (target suspect)"
            ),
        )

    # Step 6 — target-role pruning (§3.3). Keep only baseline-self-reanchor-
    # confident roles that also have a rank in the forced build.
    target_roles = sorted(
        ig for ig in inp.self_reanchored_roles if ig in inp.forced_ranks
    )
    if len(target_roles) < 2:
        return _target(
            inp, Routing.UNANCHORABLE,
            class_evidence=(
                f"only {len(target_roles)} role(s) self-reanchor confidently; "
                f"Kendall needs >= 2 pairs"
            ),
        )
    order_target = {ig: inp.forced_ranks[ig] for ig in target_roles}

    # Step 7 — derive-twice determinism.
    hashes = inp.forced_decisions_sha256
    if len(hashes) < 2 or len(set(hashes)) != 1:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            order_target=order_target, target_roles=target_roles,
            class_evidence=(
                "derive-twice DECISIONS hashes differ: nondeterministic forced "
                "build (DLL/hook fault to investigate, never averaged)"
            ),
        )

    # All gates passed -> directed.
    return _target(
        inp, Routing.DIRECTED,
        order_target=order_target, target_roles=target_roles,
    )
```

- [ ] **Step 4: Run classifier tests to verify they pass**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/mwcc_debug/test_order_target_derive.py -q --no-cov`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit the pure classifier**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/mwcc_debug/order_target_derive.py tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py && git commit -m "feat(mwcc-debug): pure order-target derivation classifier (T3 core)"
```

- [ ] **Step 6: Write the failing CLI test**

Create `tools/melee-agent/tests/cli/test_order_target_cli.py`. This test invokes the command through Typer's `CliRunner` with the collector monkeypatched so no mwcc runs (the real collector is exercised live in T12, out of this plan). It pins: directed exit 0 + a written YAML file; not_order_class exit 4 + no YAML written (no directed artifact to persist a campaign on, but the classification is printed).

```python
import json

from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.mwcc_debug.order_target_derive import DeriveInputs
from src.search.directed.order_target import OrderTarget, Routing

runner = CliRunner()


def _directed_inputs():
    return DeriveInputs(
        function="mnDiagram_OnFrame", unit="melee/mn/mndiagram", class_id=0,
        checkdiff_classification="register",
        phys_target={28: 29, 29: 28}, phys_conflicts=[],
        force_iter_first=[46, 28, 29], applied_positions={46: 0, 28: 4, 29: 6},
        forced_class_clean=True, forced_ranks={46: 1, 28: 5, 29: 7},
        baseline_ig_set={46, 28, 29}, forced_ig_set={46, 28, 29},
        self_reanchored_roles={28, 29}, unscored_roles=[],
        forced_decisions_sha256=["h", "h"],
        baseline_source_sha256="s", baseline_pcdump_sha256="p",
    )


def _conflict_inputs():
    inp = _directed_inputs()
    inp.phys_conflicts = [{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]
    return inp


def test_order_target_directed_writes_yaml_exit_0(tmp_path, monkeypatch):
    out = tmp_path / "OnFrame.yaml"
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _directed_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    loaded = OrderTarget.load_yaml(out)
    assert loaded.routing == Routing.DIRECTED.value
    assert loaded.target_roles == [28, 29]


def test_order_target_not_order_class_exit_4_no_yaml(tmp_path, monkeypatch):
    out = tmp_path / "OnFrame.yaml"
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _conflict_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--out", str(out),
    ])
    assert result.exit_code == 4, result.output
    assert "not_order_class" in result.output
    assert not out.exists()


def test_order_target_json_emits_full_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _directed_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["routing"] == "directed"
    assert payload["order_target"] == {"28": 5, "29": 7}
```

- [ ] **Step 7: Run the CLI test to verify it fails**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/cli/test_order_target_cli.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'src.cli.debug' has no attribute '_collect_order_target_inputs'` (and the `order-target` subcommand does not exist).

- [ ] **Step 8: Implement the collector + CLI command**

In `tools/melee-agent/src/cli/debug/__init__.py`, add the collector and the command. Place the collector helper near the other `_run_force_vector_auto_verify`/`_build_match_iter_first_target_vector` helpers (search for `def _run_force_vector_auto_verify` ~line 1502 and add the collector just above it), and register the command in the `target_app` block (search for `@target_app.command(name="match-iter-first")` ~line 13393 and add the new command just before it).

First, add the collector helper (this is the live orchestration; it is monkeypatched out in tests). Insert above `def _run_force_vector_auto_verify`:

```python
def _collect_order_target_inputs(
    *,
    function: str,
    unit: str,
    class_id: int,
    melee_root: Path,
    checkdiff_timeout: float,
):
    """Collect the §4.2 tool outputs for order-target derivation.

    LIVE orchestration of the four existing tools. This function is the seam
    the unit tests monkeypatch; the live end-to-end path is exercised in the
    pool census (out of this plan). It returns a DeriveInputs.

    NOTE: this performs real compiles (a register-only checkdiff, a
    force-phys-from-diff, a match-iter-first, and TWO forced dumps under the
    repo build lock). Each forced dump is a full TU compile.
    """
    import hashlib

    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events
    from src.mwcc_debug.order_target_derive import DeriveInputs
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.mwcc_debug.role_reanchor import reanchor_descs
    from src.search.directed.order_metric import colorgraph_ranks

    tu_c = melee_root / "src" / f"{unit}.c"

    # Step 1 — register-only checkdiff (classification string).
    checkdiff_payload, _src = _read_force_phys_checkdiff_payload(
        function=function, melee_root=melee_root,
        checkdiff_json=None, checkdiff_timeout=checkdiff_timeout,
    )
    checkdiff_classification = checkdiff_payload.get("classification") or "unknown"

    # Step 2 — force-phys-from-diff: reuse the same derivation the CLI command
    # uses. Build the vector + conflicts from the pre-coloring pcdump.
    pcdump_path = _resolve_pcdump_path(None, function, melee_root, require_fresh=True)
    pcdump_text = pcdump_path.read_text()
    fn = next((f for f in parse_pcdump(pcdump_text) if f.name == function), None)
    pre_pass = fn.last_precolor_pass() if fn else None
    events_fn = find_function(parse_hook_events(pcdump_text), function)
    target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
    current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
    vector = _derive_force_phys_from_register_diff_lines(
        target_asm, current_asm, pre_pass, events_fn,
    )
    phys_target = {int(k): int(v) for k, v in vector["force_phys"].items()}
    phys_conflicts = list(vector["conflicts"])

    # Step 3 — match-iter-first recommended --force-iter-first list. Reuse the
    # target-vector builder; the ig_idx list is the order forcing set.
    asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    asm_fn = asm_extract_function(asm_path.read_text(), function)
    prologue_end = asm_parse_prologue_end(asm_fn.instructions)
    body = asm_fn.instructions[prologue_end:]
    mif_results: list[dict] = []
    for reg in _parse_match_iter_first_regs("gpr-callee"):
        expected_def = asm_find_first_def(body, target_reg=reg.number, reg_kind=reg.kind)
        if expected_def is None:
            continue
        pos, expected_ist = expected_def
        match = match_virtual_for_expected_def(
            expected_ist=expected_ist, expected_position=pos,
            pre_pass=pre_pass, reg_kind=reg.kind,
        )
        if match is not None:
            mif_results.append({"status": "ok", "ig_idx": match.ig_idx})
    force_iter_first = list(dict.fromkeys(
        r["ig_idx"] for r in mif_results if r.get("status") == "ok"
    ))

    # Helper: run a forced dump and return (ranks{ig:rank}, ig_set, decisions_sha).
    def _forced_readback() -> tuple[dict, set, str]:
        out_path = (
            tu_c.parent
            / f".{function}.order-target.{os.getpid()}.{int(time.time()*1000)}.pcdump.txt"
        )
        ig_csv = ",".join(str(i) for i in force_iter_first)
        cmd = _build_match_iter_first_auto_verify_cmd(
            src_path=tu_c, ig_csv=ig_csv, function=function, output_path=out_path,
        )
        _run_auto_verify_command_with_status(
            cmd, cwd=melee_root / "tools" / "melee-agent",
            status_label=f"order-target forced dump {function}",
        )
        text = out_path.read_text()
        out_path.unlink(missing_ok=True)
        ranks = colorgraph_ranks(text, function, class_id=class_id)
        fev = find_function(parse_hook_events(text), function)
        matching = [s for s in (fev.colorgraph_sections if fev else [])
                    if s.class_id == class_id]
        section = matching[-1] if matching else None
        ig_set = {d.ig_idx for d in section.decisions} if section else set()
        sha = hashlib.sha256(
            "\n".join(f"{d.iter_idx}:{d.ig_idx}:{d.assigned_reg}"
                      for d in (section.decisions if section else [])).encode()
        ).hexdigest()
        return ranks, ig_set, sha

    forced_ranks, forced_ig_set, sha1 = _forced_readback()
    applied_positions = {ig: forced_ranks[ig] - 1 for ig in force_iter_first if ig in forced_ranks}

    # Step 4 — class-partition gate: re-run checkdiff on the forced build.
    # Reuse the auto-verify match% delta as the proxy: a clean forced build
    # eliminates the class residual. We treat classification "matched"/100% as
    # clean. The forced dump already wrote/restored the TU; re-read match%.
    forced_class_clean = _order_target_forced_class_clean(
        function=function, melee_root=melee_root,
        force_iter_first=force_iter_first, class_id=class_id,
        checkdiff_timeout=checkdiff_timeout,
    )

    # Step 5 baseline ig-set + step 6 self-reanchor on the BASELINE compile.
    baseline_compile = Compile.from_text(pcdump_text, function, tu_c.read_text())
    baseline_descs = build_descriptors(baseline_compile, class_id=class_id)
    baseline_ig_set = set(colorgraph_ranks(pcdump_text, function, class_id=class_id).keys())
    desired = {ig: phys for ig, phys in phys_target.items()}
    self_ra = reanchor_descs(baseline_descs, baseline_descs, desired, class_id=class_id)
    self_reanchored_roles = {orig for _new, orig in self_ra.matched.items()}
    unscored_roles = [
        {"ig": ig, "reason": status}
        for ig, status in self_ra.diagnostics.items()
        if ig in phys_target
    ]

    # Step 7 — derive twice.
    _r2, _s2, sha2 = _forced_readback()

    return DeriveInputs(
        function=function, unit=unit, class_id=class_id,
        checkdiff_classification=checkdiff_classification,
        phys_target=phys_target, phys_conflicts=phys_conflicts,
        force_iter_first=force_iter_first, applied_positions=applied_positions,
        forced_class_clean=forced_class_clean, forced_ranks=forced_ranks,
        baseline_ig_set=baseline_ig_set, forced_ig_set=forced_ig_set,
        self_reanchored_roles=self_reanchored_roles, unscored_roles=unscored_roles,
        forced_decisions_sha256=[sha1, sha2],
        baseline_source_sha256=hashlib.sha256(tu_c.read_bytes()).hexdigest()[:32],
        baseline_pcdump_sha256=hashlib.sha256(pcdump_text.encode()).hexdigest()[:32],
    )


def _order_target_forced_class_clean(
    *, function: str, melee_root: Path, force_iter_first: list,
    class_id: int, checkdiff_timeout: float,
) -> bool:
    """Return True if the forced-ORDER build byte-eliminates the targeted class
    residual. Proxy: run checkdiff on the forced build and treat a register-free
    (matched) result for the target class as clean. Conservative: any non-clean
    classification returns False (routes not_order_class)."""
    from src.mwcc_debug.order_target_derive import DeriveInputs  # noqa: F401
    # The forced compile + checkdiff is the live oracle; the census task wires
    # the exact integrated-checkdiff call. For derivation we re-use the
    # force-vector auto-verify union status as the cleanliness signal.
    src_path = melee_root / "src" / f"{function_unit(function, melee_root)}.c"  # see note
    entries = _parse_force_vector(
        ",".join(f"ig{ig}:iter-first" for ig in force_iter_first)
    )
    result = _run_force_vector_auto_verify(
        src_path=src_path, function=function, entries=entries,
        melee_root=melee_root, checkdiff_timeout=checkdiff_timeout,
        run_diagnostic_probes=False,
    )
    union = result.get("union") or {}
    return union.get("status") == "match"
```

> Implementation note for Step 8: `_order_target_forced_class_clean` references a `function_unit(...)` resolver — replace that line with the existing `_find_unit_for_function(function, melee_root)` call already used throughout this module (it returns the unit string). Concretely:
> ```python
>     unit = _find_unit_for_function(function, melee_root)
>     src_path = melee_root / "src" / f"{unit}.c"
> ```
> The collector is monkeypatched in tests, so its exact live wiring is validated in T12 (census), not here; the only contract this plan's tests assert is the function name and signature.

Now register the command. Insert just above `@target_app.command(name="match-iter-first")`:

```python
@target_app.command(name="order-target")
def order_target_cmd(
    function: Annotated[
        str, typer.Option("--function", "-f", help="Function to derive (required)."),
    ],
    unit: Annotated[
        Optional[str],
        typer.Option("--unit", "-u",
                     help="TU path relative to src/ (e.g. melee/mn/mndiagram). "
                          "Auto-resolves via report.json if omitted."),
    ] = None,
    class_id: Annotated[
        int, typer.Option("--class-id", help="Register class (0=GPR)."),
    ] = 0,
    out: Annotated[
        Optional[Path],
        typer.Option("--out",
                     help="Where to write the OrderTarget YAML on a directed "
                          "result. Default: docs/superpowers/order-targets/"
                          "<function>.yaml. No file is written for non-directed "
                          "routings."),
    ] = None,
    checkdiff_timeout: Annotated[
        float, typer.Option("--checkdiff-timeout", help="Per-checkdiff timeout."),
    ] = 60.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit the full artifact as JSON."),
    ] = False,
) -> None:
    """Derive a proven order-distance target (the §4.2 class partition).

    Runs the pipeline end-to-end and persists an OrderTarget on a `directed`
    result. Every failure mode is a NAMED routing, not an error; the exit code
    mirrors routing: 0 directed, 3 unanchorable, 4 not_order_class,
    5 force_cap_blocked, 6 unstable_target.
    """
    from src.mwcc_debug.order_target_derive import derive_order_target
    from src.search.directed.order_target import (
        Routing, validate_order_target,
    )

    melee_root = DEFAULT_MELEE_ROOT
    resolved_unit = unit or _find_unit_for_function(function, melee_root)
    if resolved_unit is None:
        typer.echo(
            f"function '{function}' not found in report.json; pass --unit.",
            err=True,
        )
        raise typer.Exit(2)

    inputs = _collect_order_target_inputs(
        function=function, unit=resolved_unit, class_id=class_id,
        melee_root=melee_root, checkdiff_timeout=checkdiff_timeout,
    )
    target = derive_order_target(inputs)

    if json_out:
        from dataclasses import asdict
        print(json.dumps(asdict(target), indent=2, default=list))
    else:
        print(f"Function: {target.function}")
        print(f"Unit:     {target.unit}")
        print(f"Routing:  {target.routing}")
        if target.class_evidence:
            print(f"Evidence: {target.class_evidence}")
        if target.routing == Routing.DIRECTED.value:
            print(f"Target roles: {target.target_roles}")
            print(f"Order vector: {target.order_target}")
            if target.unscored_roles:
                print(f"Unscored residual: {target.unscored_roles}")

    if target.routing == Routing.DIRECTED.value:
        validate_order_target(target)
        out_path = out or (
            melee_root / "docs" / "superpowers" / "order-targets"
            / f"{target.function}.yaml"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target.save_yaml(out_path)
        if not json_out:
            print(f"Wrote {out_path}")

    raise typer.Exit(target.exit_code())
```

- [ ] **Step 9: Run the CLI test to verify it passes**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/cli/test_order_target_cli.py -q --no-cov`
Expected: PASS (3 tests).

- [ ] **Step 10: Verify the legacy sibling was NOT touched + the CLI imports clean**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git status --porcelain tools/melee-agent/src/cli/debug.py tools/melee-agent/src/search/cli.py && cd tools/melee-agent && python -c "import src.cli.debug as d; print('order-target' in [c.name for c in d.target_app.registered_commands])"`
Expected: the first command prints NOTHING (legacy siblings untouched); the second prints `True`.

- [ ] **Step 11: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/cli/test_order_target_cli.py && git commit -m "feat(cli): debug target order-target derivation command (T3)"
```

---

### Task 5: Generalize `CandidateScore` / `score_candidate_reanchored` to an arbitrary role set

(Implemented before T4 because T4's order branch calls this generalized core. The task is numbered T5 to match the spec.)

Today `CandidateScore` is hardcoded to the pilot's two roles (`rank33`/`rank40`) and `score_candidate_reanchored` defaults to the 9ACC constants. Generalize it to an arbitrary `order_target`/`phys_target` role set, returning `ranks_by_role: {orig_ig: rank}` and a Kendall `order_distance` computed via the role-matched `metric.order_distance`. Add the §3.3 coverage check: a candidate is valid iff EVERY target role round-trip-reanchors (coverage == 1.0 over the target-role set) AND ≥2 roles are anchored; otherwise `valid=False, invalid_reason="target_role_lost"`. Keep the old `rank33`/`rank40` and `score_9acc` names working as thin shims so existing tests and callers don't break.

**Files:**
- Modify: `tools/melee-agent/src/search/directed/order_metric.py:204-374`
- Test: `tools/melee-agent/tests/search/directed/test_order_metric.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/melee-agent/tests/search/directed/test_order_metric.py`:

```python
# ---------------------------------------------------------------------------
# Generalized score_candidate_reanchored (order-distance directed search, T5)
# ---------------------------------------------------------------------------

class TestGeneralizedCandidateScore:
    def _pc(self, decisions):
        return _make_pcdump("mnDiagram_OnFrame", decisions)

    def _three_role_ref(self):
        return {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
            31: _make_role_descriptor(31, "addi r#,r#,0", False, "c", assigned_reg=30),
        }

    def test_arbitrary_roles_kendall_zero_when_in_target_order(self):
        # Target order: ig28 earlier (rank 5) than ig29 (rank 7). Candidate matches.
        pc = self._pc([(4, 28, 29), (6, 29, 28)])  # rank5=iter4, rank7=iter6
        ref = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7}, phys_target={28: 29, 29: 28},
                )
        assert result.valid is True
        assert result.ranks_by_role == {28: 5, 29: 7}
        assert result.order_distance == 0
        assert result.coverage == 1.0

    def test_kendall_one_when_pair_inverted(self):
        # Candidate has ig28 LATER than ig29 -> one inversion vs target.
        pc = self._pc([(6, 28, 29), (4, 29, 28)])
        ref = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7}, phys_target={28: 29, 29: 28},
                )
        assert result.valid is True
        assert result.order_distance == 1

    def test_target_role_lost_is_invalid_not_zero(self):
        # §3.3 hole: a candidate that LOSES a target role must be invalid, never 0.
        ref = self._three_role_ref()
        cand_only_two = {
            28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29),
            29: _make_role_descriptor(29, "li r#,0", False, "b", assigned_reg=28),
        }  # ig31 GONE
        pc = self._pc([(4, 28, 29), (6, 29, 28)])
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = cand_only_two
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5, 29: 7, 31: 9}, phys_target={28: 29, 29: 28, 31: 30},
                )
        assert result.valid is False
        assert result.invalid_reason == "target_role_lost"
        assert result.order_distance is None

    def test_fewer_than_two_anchored_is_invalid(self):
        ref = {28: _make_role_descriptor(28, "mr r#,r#", True, "a", assigned_reg=29)}
        pc = self._pc([(4, 28, 29)])
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(
                    pc, ref, function="mnDiagram_OnFrame",
                    order_target={28: 5}, phys_target={28: 29},
                )
        assert result.valid is False
        assert result.invalid_reason == "target_role_lost"

    def test_legacy_rank33_rank40_shim_still_populated(self):
        # The 9ACC two-role path keeps the back-compat rank33/rank40 fields.
        pc = _make_pcdump("grIceMt_801F9ACC", [(2, 40, 29), (4, 33, 27)])
        ref = _ref_descs_9acc_baseline()
        from unittest.mock import patch
        with patch("src.search.directed.order_metric.Compile"):
            with patch("src.search.directed.order_metric.build_descriptors") as bd:
                bd.return_value = ref
                result = score_candidate_reanchored(pc, ref)
        assert result.valid is True
        assert result.rank33 == 5
        assert result.rank40 == 3
        assert result.ranks_by_role == {33: 5, 40: 3}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_metric.py::TestGeneralizedCandidateScore -q --no-cov`
Expected: FAIL — `AttributeError: 'CandidateScore' object has no attribute 'ranks_by_role'` (and `coverage`).

- [ ] **Step 3: Generalize the dataclass + scorer**

In `tools/melee-agent/src/search/directed/order_metric.py`, replace the `CandidateScore` dataclass (lines 204-229) AND the `score_candidate_reanchored` function (lines 232-374) with the following. Import the role-matched Kendall metric at the top of the function body (keep module imports as-is).

Replace `CandidateScore`:

```python
@dataclass(frozen=True)
class CandidateScore:
    """Result of score_candidate_reanchored for one mutated-source compile.

    Generalized (order-distance directed search, T5) to an arbitrary target-role
    set.  ``ranks_by_role`` maps each original target ig to its 1-based rank in
    the candidate's (reanchored) coloring.  ``order_distance`` is the role-matched
    Kendall pairwise-inversion distance vs the target order (0 == every pair in
    target relative order).  ``coverage`` is the fraction of target roles that
    round-trip-reanchored.

    §3.3 validity: a candidate is ``valid`` iff coverage == 1.0 over the target
    roles AND >= 2 roles anchored.  Otherwise ``valid=False`` with
    ``invalid_reason="target_role_lost"`` — losing a target role can NEVER look
    like progress (closes the test_metric.py:32 hollowing hole at the objective).

    Back-compat: ``rank33``/``rank40`` remain populated for the 9ACC two-role
    pilot so older callers/tests keep working.
    """

    valid: bool
    invalid_reason: Optional[str]
    ranks_by_role: Optional[dict]
    order_distance: Optional[int]
    phys_matched: Optional[int]
    coverage: Optional[float]
    # --- 9ACC back-compat shims ---
    rank33: Optional[int] = None
    rank40: Optional[int] = None
```

Replace `score_candidate_reanchored` with:

```python
def score_candidate_reanchored(
    cand_pcdump_text: str,
    ref_descs: dict,
    *,
    function: str = "grIceMt_801F9ACC",
    class_id: int = 0,
    order_target: Optional[dict] = None,
    phys_target: Optional[dict] = None,
    cand_source: str = "",
) -> CandidateScore:
    """Identity-safe order-distance scorer for a mutated-source candidate.

    Mutating source can renumber IG nodes.  This resolves each target role's NEW
    ig via ``reanchor_descs``, reads ranks/assignments at the reanchored nodes,
    and computes the role-matched Kendall ``order_distance`` vs ``order_target``.

    §3.3 validity (the objective rule): every target role must round-trip-
    reanchor (coverage == 1.0) AND >= 2 roles must anchor, else the candidate is
    ``valid=False, invalid_reason="target_role_lost"`` — never ranked, never 0.

    This is the SHARED scoring core used by the scorer's order branch (T4) and
    the kill-switch harness (T7), so both exercise the same path.
    """
    from src.search.directed.metric import order_distance as kendall_distance

    _order_target = order_target if order_target is not None else NINEACC_ORDER_TARGET
    _phys_target = phys_target if phys_target is not None else NINEACC_PHYS_TARGET

    def _invalid(reason: str) -> CandidateScore:
        return CandidateScore(
            valid=False, invalid_reason=reason, ranks_by_role=None,
            order_distance=None, phys_matched=None, coverage=None,
            rank33=None, rank40=None,
        )

    try:
        cand_compile = Compile.from_text(cand_pcdump_text, function, source=cand_source)
    except Exception as exc:
        return _invalid(f"compile_parse_failed: {exc}")

    cand_descs = build_descriptors(cand_compile, class_id=class_id)
    desired = {orig_ig: phys for orig_ig, phys in _phys_target.items()}
    ra = reanchor_descs(ref_descs, cand_descs, desired, class_id=class_id)
    orig_to_new: dict[int, int] = {orig: new for new, orig in ra.matched.items()}

    # §3.3 coverage: every target role must round-trip-reanchor.
    target_igs = list(_order_target)
    anchored = [ig for ig in target_igs if ig in orig_to_new]
    coverage = len(anchored) / len(target_igs) if target_igs else 0.0
    if coverage < 1.0 or len(anchored) < 2:
        return _invalid("target_role_lost")

    # Read ranks at the reanchored ig numbers.
    cand_ranks_raw = colorgraph_ranks(cand_pcdump_text, function, class_id=class_id)
    ranks_by_role: dict[int, int] = {}
    for orig_ig, new_ig in orig_to_new.items():
        if orig_ig in _order_target and new_ig in cand_ranks_raw:
            ranks_by_role[orig_ig] = cand_ranks_raw[new_ig]

    # A target role that reanchored but is absent from the colorgraph (spilled
    # out of the decision set) breaks coverage just like a lost role.
    if len([ig for ig in target_igs if ig in ranks_by_role]) < len(target_igs):
        return _invalid("target_role_lost")
    for orig_ig in target_igs:
        desc = cand_descs.get(orig_to_new[orig_ig])
        if desc is not None and desc.spilled:
            return _invalid("target_role_lost")

    # Role-matched Kendall distance: build cand/objective iter maps keyed by the
    # ORIGINAL ig (ranks are 1-based positions; relative order is what Kendall
    # consumes, so using ranks directly is equivalent to using iter_idx).
    od = kendall_distance(ranks_by_role, _order_target)

    # Phys hits at reanchored igs.
    phys_hits = 0
    dec_by_ig = {d.ig_idx: d for d in _iter_decisions(cand_pcdump_text, function, class_id)}
    for orig_ig, desired_reg in _phys_target.items():
        new_ig = orig_to_new.get(orig_ig)
        dec = dec_by_ig.get(new_ig) if new_ig is not None else None
        if dec is not None and dec.assigned_reg == desired_reg:
            phys_hits += 1

    return CandidateScore(
        valid=True, invalid_reason=None, ranks_by_role=ranks_by_role,
        order_distance=od, phys_matched=phys_hits, coverage=coverage,
        rank33=ranks_by_role.get(33), rank40=ranks_by_role.get(40),
    )
```

- [ ] **Step 4: Run the full order_metric suite to verify pass + no regressions**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_metric.py -q --no-cov`
Expected: PASS. The existing `TestScoreCandidateReanchored` tests still pass via the `rank33`/`rank40` shims; the new `TestGeneralizedCandidateScore` tests pass.

> Note: the existing `test_baseline_identity_stable_order_distance_4` asserts `order_distance == 4` using the OLD sum-of-deltas metric, while the generalized scorer now uses **Kendall** (which is 1 for that inverted two-role pair, not 4). If that assertion fails, update it in this step: change `assert result.order_distance == 4` to `assert result.order_distance == 1` and `assert result.order_distance == 0` stays 0 for the target case (Kendall agrees with sum-of-deltas at 0). The four 9ACC tests that assert `order_distance == 4` are the only ones affected; flip each `== 4` to `== 1` and leave `phys_matched`/`rank*` assertions unchanged.

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/order_metric.py tools/melee-agent/tests/search/directed/test_order_metric.py && git commit -m "feat(directed): generalize CandidateScore to arbitrary roles + §3.3 coverage validity (T5)"
```

---

### Task 4: Scorer order-mode branch + §3.3 hardened validity

Add the `objective_mode == "order"` branch to `score_directed`. In order mode the gate signal fields (`order_distance`/`displacement`) are populated from the role-matched Kendall distance vs the proven vector (NOT phys-match), and the §3.3 validity rule applies: a candidate that loses a target role is `invalid` with reason `target_role_lost`. **Crucially for A+B: this only changes the scorer's exposed fields; it does NOT touch gate/scheduler polarity** (those still read `displacement` higher-is-better — that flip is Plan C). The order branch reuses the generalized scoring core (T5) so the scorer and the kill switch exercise the same path. The default `objective_mode == "phys"` path is byte-for-byte unchanged.

**Files:**
- Modify: `tools/melee-agent/src/search/directed/scorer.py:143-265`
- Test: `tools/melee-agent/tests/search/directed/test_scorer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/melee-agent/tests/search/directed/test_scorer.py`:

```python
# --- order-mode branch (order-distance directed search, T4) ---

def _order_objective(order_target, phys_target, roles_n=2):
    class _RT: pass
    rt = _RT(); rt.roles = [object()] * roles_n; rt.function = "mnDiagram_OnFrame"
    return DirectedObjective(
        search_target=None, role_target=rt, baseline_compile=None,
        baseline_pcdump_path=None, baseline_source_hash="h", class_id=0,
        objective_iter_by_original_ig=order_target, proof_force_phys=phys_target,
        objective_mode="order", order_target_roles=tuple(sorted(order_target)),
    )


def test_order_mode_scores_kendall_distance(tmp_path, monkeypatch):
    # Stub the generalized core so no mwcc runs.
    from src.search.directed import scorer as scorer_mod
    from src.search.directed.order_metric import CandidateScore

    def fake_score(cand_pcdump_text, ref_descs, **kw):
        return CandidateScore(
            valid=True, invalid_reason=None, ranks_by_role={28: 5, 29: 7},
            order_distance=0, phys_matched=2, coverage=1.0,
        )
    monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", fake_score, raising=False)

    pipe = DirectedScorePipeline(
        analyze=lambda t, c, class_id=0: (_State(_Case("B")), object(), _Re({1: 28, 2: 29})),
        compile_from_text=lambda art: object(),
        decisions_of=lambda c: {1: _Dec(4, 29), 2: _Dec(6, 28)},
        classify=lambda prev, curr, **k: type("L", (), {"value": "SAME"})(),
    )
    obj = _order_objective({28: 5, 29: 7}, {28: 29, 29: 28})
    out = pipe.score_directed(_art(tmp_path), DirectedScoringCall(obj, _parent()))
    assert out.status == "ok"
    assert out.directed_meta.valid is True
    assert out.directed_meta.order_distance == 0


def test_order_mode_target_role_lost_is_invalid(tmp_path, monkeypatch):
    from src.search.directed import scorer as scorer_mod
    from src.search.directed.order_metric import CandidateScore

    def fake_score(cand_pcdump_text, ref_descs, **kw):
        return CandidateScore(
            valid=False, invalid_reason="target_role_lost", ranks_by_role=None,
            order_distance=None, phys_matched=None, coverage=0.5,
        )
    monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", fake_score, raising=False)

    pipe = DirectedScorePipeline(
        analyze=lambda t, c, class_id=0: (_State(_Case("B")), object(), _Re({1: 28})),
        compile_from_text=lambda art: object(),
        decisions_of=lambda c: {1: _Dec(4, 29)},
        classify=lambda prev, curr, **k: type("L", (), {"value": "SAME"})(),
    )
    obj = _order_objective({28: 5, 29: 7}, {28: 29, 29: 28})
    out = pipe.score_directed(_art(tmp_path), DirectedScoringCall(obj, _parent()))
    assert out.status == "invalid"
    assert out.directed_meta.invalid_reason == "target_role_lost"


def test_phys_mode_unchanged_by_order_branch(tmp_path):
    # The default phys path must be byte-identical: 9ACC wall -> displacement 0/2.
    out = _pipe("B").score_directed(_art(tmp_path), DirectedScoringCall(_objective(), _parent()))
    assert out.status == "ok"
    assert out.directed_meta.case == "B"
    # phys objective with empty proof falls back to role count; gate field present.
    assert hasattr(out.directed_meta, "order_distance")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_scorer.py -q --no-cov -k "order_mode or phys_mode_unchanged"`
Expected: FAIL — `test_order_mode_scores_kendall_distance` produces a phys-match score (the branch doesn't exist yet), so `order_distance` is not 0 / validity not applied.

- [ ] **Step 3: Add the order branch**

In `tools/melee-agent/src/search/directed/scorer.py`, add a module-level import near the top imports (after the `from src.search.directed.metric import (...)` block, ~line 25):

```python
from src.search.directed.order_metric import score_candidate_reanchored
```

Then, inside `score_directed`, immediately AFTER the coverage gate (after line 192, the `if len(reanchor.matched) / n_roles < self._coverage_floor:` block) and BEFORE `# --- compute decisions ---` (line 194), insert the order-mode branch:

```python
        # --- ORDER-MODE BRANCH (order-distance directed search, T4) ----------
        # When objective_mode == "order", the gate-signal fields are sourced
        # from the role-matched Kendall distance vs the PROVEN order vector (not
        # phys-match), with the §3.3 validity rule (a lost target role is
        # invalid, never a perfect 0).  This EXPOSES the order objective; it
        # does NOT change gate/scheduler polarity (Plan C).  The default "phys"
        # path below is unchanged.
        if getattr(obj, "objective_mode", "phys") == "order":
            return self._score_order(art, call, compile=compile,
                                     state=state, reanchor=reanchor)

```

Now add the `_score_order` method to the `DirectedScorePipeline` class. Insert it directly after `score_directed` ends (after line 265, before `# _attribution`):

```python
    # ------------------------------------------------------------------
    # _score_order — the objective_mode == "order" scoring path.
    # ------------------------------------------------------------------

    def _score_order(self, art: Any, call: DirectedScoringCall, *,
                     compile: Any, state: Any, reanchor: Any) -> Any:
        """Score a candidate against the PROVEN order vector via the shared
        generalized scorer (T5).  Lower order_distance is better; the §3.3
        validity rule rejects candidates that lose a target role.

        Polarity note: this populates the SAME meta fields the phys path uses
        (order_distance/displacement) but with order semantics.  The gate and
        scheduler still read them higher-is-better; flipping that comparator is
        Plan C (T8/T9).  For A+B the kill-switch reads the order_distance field
        directly, so the scorer exposing it is sufficient.
        """
        obj = call.objective
        parent_state = call.parent_state
        order_target = dict(obj.objective_iter_by_original_ig)
        phys_target = dict(obj.proof_force_phys)
        pcdump_text = art.pcdump_path.read_text(encoding="utf-8")
        source_text = art.source_blob.read_text(encoding="utf-8")
        ref_descs = self._order_ref_descs(obj)

        cs = score_candidate_reanchored(
            pcdump_text, ref_descs, function=obj.role_target.function,
            class_id=obj.class_id, order_target=order_target,
            phys_target=phys_target, cand_source=source_text,
        )
        if not cs.valid:
            return self._invalid(art, call, cs.invalid_reason or "target_role_lost")

        case = _case_str(state.fact.case)
        n_target = len(order_target)
        n_anchored = len(cs.ranks_by_role or {})
        applied_mutator, non_actionable = self._attribution(art, parent_state)
        parent_id = (
            getattr(call.parent_state.current_best, "candidate_id", None)
            if call.parent_state.current_best is not None else None
        )
        meta = DirectedMeta(
            candidate_id=art.candidate_id,
            source_hash=art.source_hash,
            iteration=0,
            parent_id=parent_id,
            parent_state_id=parent_state.state_id,
            valid=True,
            invalid_reason=None,
            case=case,
            label="order",
            order_distance=cs.order_distance,
            displacement=float(cs.phys_matched or 0) / max(n_target, 1),
            displacement_delta=0.0,
            reanchor_matched=n_anchored,
            reanchor_total=n_target,
            diagnosis_chars=len(case),
            applied_mutator=applied_mutator,
            directed_scalar=float(cs.order_distance),
            proof_assignments=None,
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
            iter_order_distance=cs.order_distance,
            iter_displacement=None,
        )
        return replace(art, directed_score=float(cs.order_distance),
                       directed_meta=meta, status="ok")

    def _order_ref_descs(self, obj: Any) -> dict:
        """Build the baseline identity reference descriptors for order scoring.

        Prefer the objective's pre-built baseline_compile; fall back to building
        from the baseline pcdump path.  Cached per-objective is unnecessary here
        (one build per candidate is dwarfed by the candidate compile)."""
        from src.mwcc_debug.role_descriptor import Compile, build_descriptors
        bc = obj.baseline_compile
        if bc is not None:
            return build_descriptors(bc, class_id=obj.class_id)
        if obj.baseline_pcdump_path is not None:
            from pathlib import Path
            text = Path(obj.baseline_pcdump_path).read_text(encoding="utf-8")
            src = ""
            compile = Compile.from_text(text, obj.role_target.function, src)
            return build_descriptors(compile, class_id=obj.class_id)
        return {}
```

> Note for the test's monkeypatch: `_score_order` calls the module-level name `score_candidate_reanchored` imported into `scorer.py`, so `monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", ...)` in the test patches the right reference.

- [ ] **Step 4: Run scorer tests to verify pass + no regressions**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_scorer.py -q --no-cov`
Expected: PASS (all existing phys-path tests + the 3 new order-mode tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/scorer.py tools/melee-agent/tests/search/directed/test_scorer.py && git commit -m "feat(directed): scorer order-mode branch + §3.3 validity (T4)"
```

- [ ] **Step 6: Plan-A regression gate — run the full directed + mwcc_debug suites**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed tests/mwcc_debug/test_order_target_derive.py tests/cli/test_order_target_cli.py -q --no-cov`
Expected: PASS (the full directed test directory plus the two new derivation/CLI suites — no regressions from T1-T5).

---

## Plan B — the kill switch (STOP gate)

### Task 6: Fixture creation + pre-win eligibility check (the derivation contingency)

Extract the frozen fixtures from `a527c0227` (the comma-expr win, 95.68%→97.96%) and its parent `a527c0227~1` (the pre-win base). **The win commit changes the callee-save count (stmw r20/12-saves → r21/11-saves), so the pre-win base may NOT be FULLNORM-0** — §6c's flagged contingency. T6 therefore checks eligibility FIRST: if the pre-win base routes `directed`, derive its OrderTarget; if it routes out, record the finding, promote the cardstate decl-chain witness to the gating retrodiction, and inform the orchestrator. Both outcomes are committed — never silent.

Because deriving a real pcdump requires live mwcc (slow, environment-dependent), this task **commits the fixture sources unconditionally** and writes a `PROVENANCE.md` recording the eligibility outcome. The pcdump + `order_target.yaml` fixtures are generated by a committed, reproducible script so T7 can run against frozen bytes without live compilation in CI; the script also records which witness (802427B4 or cardstate) is the gating one.

**Files:**
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/pre_win.c`
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/win.c`
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/negative_control.c`
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/PROVENANCE.md`
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/build_fixtures.sh`

- [ ] **Step 1: Extract the pre-win and win TU sources**

Run (this writes the two real TU sources at the two commits into the fixture dir):

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && mkdir -p tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4 && git show a527c0227~1:src/melee/mn/mndiagram.c > tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/pre_win.c && git show a527c0227:src/melee/mn/mndiagram.c > tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/win.c && echo "pre_win lines: $(wc -l < tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/pre_win.c); win lines: $(wc -l < tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/win.c)"
```

Expected: both files written; line counts printed (the two differ by the +4/-1 comma-expr + split-base edit).

- [ ] **Step 2: Create the negative control**

The negative control is `pre_win.c` plus ONE edit verified at freeze time to NOT improve match% — an adjacent decl-pair swap in `mnDiagram_802427B4`. The pre-win function declares (from the source read at `a527c0227~1`) the locals at the top of `mnDiagram_802427B4`. Swap the two adjacent `Vec3 pos;`-region declarations' order. Create the control by copying pre_win and swapping the first two adjacent local declarations inside the function.

Run:

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && cp tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/pre_win.c tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/negative_control.c && echo "Now MANUALLY apply one verified-non-improving adjacent decl swap inside mnDiagram_802427B4 in negative_control.c (see Step 3)."
```

- [ ] **Step 3: Apply + record the negative-control edit**

Open `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/negative_control.c`, find the top of `void mnDiagram_802427B4(...)`, and swap the order of the first two adjacent local declarations (e.g. if the source declares `s32 i;` then `Vec3 pos;` on consecutive lines, swap them to `Vec3 pos;` then `s32 i;`). This is a pure decl-order reshape with no behavioral change. The campaign history records ~12 failed reshapes on this function; an adjacent decl swap is the canonical non-improving edit.

Then verify it does NOT improve match% (this is the freeze-time verification §6c requires). Apply the control to the live TU, checkdiff, and restore:

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && cp src/melee/mn/mndiagram.c /tmp/mndiagram.orig.c && cp tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/negative_control.c src/melee/mn/mndiagram.c && (python tools/checkdiff.py mnDiagram_802427B4 --format json 2>/dev/null | python -c "import sys,json; d=json.load(sys.stdin); print('control match%:', d.get('match_percent') or d.get('fuzzy_match_percent'))") ; cp /tmp/mndiagram.orig.c src/melee/mn/mndiagram.c && echo "restored TU"
```

Expected: the control's match% prints and is NOT higher than the pre-win base (95.68%). If it is higher, pick a different adjacent decl swap and re-verify (the assertion (d) in T7 depends on this being non-improving). Record the chosen edit + its measured match% in PROVENANCE.md (Step 5).

- [ ] **Step 4: Write the reproducible fixture-build script**

Create `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/build_fixtures.sh`:

```bash
#!/usr/bin/env bash
# Regenerate the frozen pcdumps + order_target.yaml for the kill-switch fixtures.
#
# This requires a working local mwcc-debug (`melee-agent debug dump doctor`
# PASSES). It is the reproducible provenance for the *.pcdump.txt and
# order_target.yaml committed alongside the .c sources. Run from the worktree
# root. It does NOT run in CI; T7 reads the committed frozen bytes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../../../.." && pwd)"   # -> worktree root
TU="src/melee/mn/mndiagram.c"
FN="mnDiagram_802427B4"
UNIT="melee/mn/mndiagram"
cd "$ROOT"

dump_one() {
  local src="$1" out="$2"
  cp "$TU" /tmp/mndiagram.killswitch.orig.c
  cp "$src" "$TU"
  # shellcheck disable=SC2064
  trap "cp /tmp/mndiagram.killswitch.orig.c '$TU'" EXIT
  ( cd tools/melee-agent && python -m src.cli debug dump local "$ROOT/$TU" \
      --function "$FN" --output "$out" --no-cache-sync )
  cp /tmp/mndiagram.killswitch.orig.c "$TU"
  trap - EXIT
}

dump_one "$HERE/pre_win.c"          "$HERE/pre_win.pcdump.txt"
dump_one "$HERE/win.c"              "$HERE/win.pcdump.txt"
dump_one "$HERE/negative_control.c" "$HERE/negative_control.pcdump.txt"

# Eligibility check + OrderTarget derivation on the pre-win base.
# Apply pre_win, derive, restore. A directed result writes order_target.yaml;
# a non-directed result is recorded in PROVENANCE.md and the cardstate witness
# becomes the gating retrodiction (see PROVENANCE.md).
cp "$TU" /tmp/mndiagram.killswitch.orig.c
cp "$HERE/pre_win.c" "$TU"
trap "cp /tmp/mndiagram.killswitch.orig.c '$TU'" EXIT
set +e
( cd tools/melee-agent && python -m src.cli debug target order-target \
    -f "$FN" -u "$UNIT" --out "$HERE/order_target.yaml" --json ) \
    > "$HERE/derive_outcome.json" 2>&1
echo "order-target exit code: $?"
set -e
cp /tmp/mndiagram.killswitch.orig.c "$TU"
trap - EXIT
echo "Fixtures regenerated. Review derive_outcome.json for the routing."
```

Make it executable:

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && chmod +x tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/build_fixtures.sh
```

- [ ] **Step 5: Run the build script + record the eligibility outcome in PROVENANCE.md**

Run the script (live mwcc; minutes). If `debug dump doctor` does not PASS in this worktree, run `python tools/worktree-doctor.py --fix` first.

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m src.cli debug dump doctor 2>&1 | tail -3 && cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && bash tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/build_fixtures.sh 2>&1 | tail -20
```

Then create `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/PROVENANCE.md` recording the outcome verbatim. Use this template and fill the bracketed values from `derive_outcome.json` and the Step-3 control match%:

```markdown
# Kill-switch fixtures — mnDiagram_802427B4

## Sources (frozen)
- `pre_win.c`  — `src/melee/mn/mndiagram.c` at commit `a527c0227~1` (f2d654331), 95.68%.
- `win.c`      — `src/melee/mn/mndiagram.c` at commit `a527c0227`, 97.96% (comma-expr LICM
                 defeat: `pos.y = (0, mnDiagram_804DBFAC) - HSD_JObjGetTranslationY(j);`
                 + split base-pointer `p = sorted; p = p + start;`; stmw r20/12-saves →
                 r21/11-saves).
- `negative_control.c` — `pre_win.c` + ONE adjacent decl-pair swap in `mnDiagram_802427B4`:
                 [describe the exact swap]. Freeze-time match% = [X]% (NOT > 95.68% — verified
                 non-improving, satisfies assertion (d)).

## Pcdumps (frozen, regenerate via build_fixtures.sh)
- `pre_win.pcdump.txt`, `win.pcdump.txt`, `negative_control.pcdump.txt`.

## Derivation contingency outcome (§6c)
order-target on the pre-win base routed: **[ROUTING]**.

- IF `directed`: `order_target.yaml` is the gating OrderTarget. The gating
  retrodiction is mnDiagram_802427B4. The named flipping pair (assertion c) is
  [ig_a]<->[ig_b], chosen among roles that PERSIST across the win (the relabeled
  callee-save-band roles, NOT the eliminated hoisted-base node).
- IF non-directed ([not_order_class | unanchorable | force_cap_blocked]):
  FINDING — the celebrated 802427B4 win was a node-set-class win, partially
  outside this metric's class. The **cardstate fn_803ACD58 decl-chain witness**
  (src/sysdolphin/baselib/hsd_3AA7.c; commits 387983cd4 → ffad1f5ed → f2cf55b2b
  → b7013dc48, each peeling one callee-save) is PROMOTED to the gating
  retrodiction (decl reorders are pure order moves on a stable node set —
  squarely in-class). The orchestrator MUST be informed the kill-switch function
  assignment needs revisiting. The kill switch still runs (it does not silently
  pass).
```

- [ ] **Step 6: Commit the fixtures**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/ && git commit -m "test(killswitch): freeze 802427B4 pre-win/win/negative fixtures + eligibility provenance (T6)"
```

---

### Task 7: Kill-switch harness + assertions (a)-(d) + secondary witness + result doc

The harness scores the three FIXED candidate sources (`pre_win`, `win`, `negative_control`) through the SAME generalized scoring core (T5) the loop uses, against the OrderTarget derived on the pre-win base (or, if the contingency fired, against the cardstate decl-chain witness). It is mutator-independent by construction. The four assertions (§6c): (a) same anchored target-role set across pre_win/win, (b) strict descent `order_distance(win) < order_distance(pre_win)`, (c) a named target-role pair flips in the intended direction, (d) the negative control does not descend. A failure of ANY assertion is the kill switch firing — the harness writes the refutation into the result doc and the test asserts the verdict so a failed premise STOPs the campaign loudly.

**Files:**
- Create: `tools/melee-agent/src/search/directed/kill_switch.py`
- Create: `tools/melee-agent/tests/search/directed/test_kill_switch.py`
- Create: `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md` (written by the harness run)

- [ ] **Step 1: Write the failing harness unit tests (synthetic, no mwcc)**

Create `tools/melee-agent/tests/search/directed/test_kill_switch.py`. These tests drive the harness with a **fake scorer** so the four assertions are exercised deterministically without compilation; a separate `@pytest.mark.slow` test runs against the real frozen pcdumps.

```python
import os
import pytest

from src.search.directed.kill_switch import (
    KillSwitchResult,
    evaluate_kill_switch,
)
from src.search.directed.order_metric import CandidateScore


def _score(od, ranks):
    return CandidateScore(
        valid=True, invalid_reason=None, ranks_by_role=ranks,
        order_distance=od, phys_matched=0, coverage=1.0,
    )


def test_all_assertions_pass_when_win_descends():
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7}),       # pair inverted
        "win": _score(0, {21: 5, 22: 7}),           # pair correct, descends
        "negative_control": _score(1, {21: 5, 22: 7}),  # no descent
    }
    res = evaluate_kill_switch(
        scores=scores, named_pair=(21, 22),
        pre_win_pair_order=(7, 5),   # in pre_win, ig21 LATER than ig22 (inverted)
        win_pair_order=(5, 7),       # in win, ig21 earlier (correct)
    )
    assert res.passed is True
    assert res.assertion_a is True
    assert res.assertion_b is True
    assert res.assertion_c is True
    assert res.assertion_d is True


def test_fires_when_win_does_not_descend():
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7}),
        "win": _score(1, {21: 5, 22: 7}),  # NO descent
        "negative_control": _score(2, {21: 5, 22: 7}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22),
                              pre_win_pair_order=(7, 5), win_pair_order=(5, 7))
    assert res.passed is False
    assert res.assertion_b is False
    assert "strict descent" in res.failure_reason


def test_fires_when_anchor_sets_differ():
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7}),
        "win": _score(0, {21: 5, 99: 7}),  # different role anchored
        "negative_control": _score(1, {21: 5, 22: 7}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22),
                              pre_win_pair_order=(7, 5), win_pair_order=(5, 7))
    assert res.passed is False
    assert res.assertion_a is False


def test_fires_when_negative_control_descends():
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7}),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(0, {21: 5, 22: 7}),  # control improved -> false positive
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22),
                              pre_win_pair_order=(7, 5), win_pair_order=(5, 7))
    assert res.passed is False
    assert res.assertion_d is False


def test_fires_when_named_pair_does_not_flip():
    # pre_win already has the pair in the CORRECT order -> (c) cannot be the
    # intended flip even though the metric descends.
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7}),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(1, {21: 5, 22: 7}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22),
                              pre_win_pair_order=(5, 7),  # already correct in pre_win
                              win_pair_order=(5, 7))
    assert res.passed is False
    assert res.assertion_c is False


def test_invalid_candidate_fires():
    scores = {
        "pre_win": CandidateScore(False, "target_role_lost", None, None, None, 0.5),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(1, {21: 5, 22: 7}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22),
                              pre_win_pair_order=(7, 5), win_pair_order=(5, 7))
    assert res.passed is False
    assert "invalid" in res.failure_reason


_LIVE = pytest.mark.skipif(
    not os.environ.get("LIVE_KILLSWITCH"),
    reason="Set LIVE_KILLSWITCH=1 to score the real frozen pcdumps",
)


@pytest.mark.slow
@_LIVE
def test_kill_switch_on_frozen_fixtures():
    """Score the real frozen pcdumps against the frozen OrderTarget and write
    the result doc. PASS == the premise holds; FAIL == STOP (premise refuted)."""
    from pathlib import Path
    from src.search.directed.kill_switch import run_kill_switch_from_fixtures

    fixtures = Path(__file__).resolve().parents[2] / (
        "tests/fixtures/order_distance/mnDiagram_802427B4"
    )
    res = run_kill_switch_from_fixtures(fixtures)
    # The harness writes the result doc regardless of outcome.
    assert res.result_doc_path is not None and Path(res.result_doc_path).exists()
    assert res.passed, f"KILL SWITCH FIRED — premise refuted: {res.failure_reason}"
```

- [ ] **Step 2: Run the harness unit tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_kill_switch.py -q --no-cov -k "not frozen_fixtures"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.search.directed.kill_switch'`.

- [ ] **Step 3: Implement the harness**

Create `tools/melee-agent/src/search/directed/kill_switch.py`:

```python
"""Kill switch — frozen-fixture retrodiction of a known win (§6c).

The premise under test: directed order-distance descends toward a forced-ORDER-
proven target and the metric retrodicts the known mnDiagram_802427B4 win. The
kill switch scores THREE FIXED candidate sources (pre_win / win / negative
control) through the SAME generalized scoring core the loop uses, against the
OrderTarget derived on the pre-win base. It is mutator-independent.

Four assertions (all must hold, else the premise is REFUTED and the campaign
STOPs):
  (a) pre_win and win round-trip-anchor the EXACT same target-role set.
  (b) order_distance(win) < order_distance(pre_win) (both §3.3-valid).
  (c) a NAMED target-role pair is inverted in pre_win and correct in win.
  (d) order_distance(negative_control) >= order_distance(pre_win).

A failure of ANY assertion is the kill switch firing. The result is written to
docs/superpowers/results/ regardless of outcome — never silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class KillSwitchResult:
    passed: bool
    assertion_a: bool
    assertion_b: bool
    assertion_c: bool
    assertion_d: bool
    failure_reason: str
    detail: dict
    result_doc_path: Optional[str] = None


def evaluate_kill_switch(
    *,
    scores: dict,            # {"pre_win"|"win"|"negative_control": CandidateScore}
    named_pair: tuple,       # (ig_a, ig_b) — the pair that must flip
    pre_win_pair_order: tuple,  # (rank_of_ig_a, rank_of_ig_b) in pre_win
    win_pair_order: tuple,      # (rank_of_ig_a, rank_of_ig_b) in win
) -> KillSwitchResult:
    """Apply the four §6c assertions to three pre-computed CandidateScores."""
    pre = scores.get("pre_win")
    win = scores.get("win")
    neg = scores.get("negative_control")

    # All three must be §3.3-valid to even compare.
    for name, cs in (("pre_win", pre), ("win", win), ("negative_control", neg)):
        if cs is None or not cs.valid:
            reason = (
                f"{name} candidate is invalid "
                f"({getattr(cs, 'invalid_reason', 'missing')}); cannot retrodict"
            )
            return KillSwitchResult(
                False, False, False, False, False, reason,
                {"scores": {k: _cs_dict(v) for k, v in scores.items()}},
            )

    # (a) same anchored target-role set.
    a = set(pre.ranks_by_role) == set(win.ranks_by_role)

    # (b) strict descent.
    b = win.order_distance < pre.order_distance

    # (c) the named pair is inverted in pre_win and correct in win.
    ig_a, ig_b = named_pair
    pre_inverted = pre_win_pair_order[0] > pre_win_pair_order[1]   # ig_a LATER than ig_b
    win_correct = win_pair_order[0] < win_pair_order[1]            # ig_a earlier than ig_b
    pair_present = ig_a in pre.ranks_by_role and ig_b in pre.ranks_by_role \
        and ig_a in win.ranks_by_role and ig_b in win.ranks_by_role
    c = bool(pair_present and pre_inverted and win_correct)

    # (d) negative control does not descend.
    d = neg.order_distance >= pre.order_distance

    passed = a and b and c and d
    reasons = []
    if not a:
        reasons.append("assertion (a) failed: anchored target-role sets differ "
                       f"(pre={sorted(pre.ranks_by_role)} win={sorted(win.ranks_by_role)}) "
                       "— this win class is invisible to role-stable order distance")
    if not b:
        reasons.append(f"assertion (b) failed: no strict descent "
                       f"(pre={pre.order_distance} win={win.order_distance})")
    if not c:
        reasons.append("assertion (c) failed: the named pair "
                       f"{named_pair} did not flip in the intended direction "
                       f"(pre_order={pre_win_pair_order} win_order={win_pair_order})")
    if not d:
        reasons.append("assertion (d) failed: negative control descended "
                       f"(pre={pre.order_distance} neg={neg.order_distance}) "
                       "— the metric admits false positives")
    return KillSwitchResult(
        passed, a, b, c, d, "; ".join(reasons),
        {
            "pre_win": _cs_dict(pre), "win": _cs_dict(win),
            "negative_control": _cs_dict(neg), "named_pair": list(named_pair),
            "pre_win_pair_order": list(pre_win_pair_order),
            "win_pair_order": list(win_pair_order),
        },
    )


def _cs_dict(cs: Any) -> dict:
    if cs is None:
        return {"present": False}
    return {
        "valid": cs.valid, "invalid_reason": cs.invalid_reason,
        "order_distance": cs.order_distance,
        "ranks_by_role": cs.ranks_by_role, "coverage": cs.coverage,
    }


def run_kill_switch_from_fixtures(fixtures_dir: Any) -> KillSwitchResult:
    """Score the frozen pcdumps against the frozen OrderTarget, apply the four
    assertions, and WRITE the result doc (pass or fail). Live-bytes path used by
    the @slow test and any future CLI; needs the frozen pcdumps + order_target.yaml
    that build_fixtures.sh produced.
    """
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.search.directed.order_metric import score_candidate_reanchored
    from src.search.directed.order_target import OrderTarget

    fixtures = Path(fixtures_dir)
    target = OrderTarget.load_yaml(fixtures / "order_target.yaml")
    function = target.function

    # Identity reference = the pre-win baseline compile.
    pre_win_pc = (fixtures / "pre_win.pcdump.txt").read_text(encoding="utf-8")
    pre_win_src = (fixtures / "pre_win.c").read_text(encoding="utf-8")
    ref_compile = Compile.from_text(pre_win_pc, function, pre_win_src)
    ref_descs = build_descriptors(ref_compile, class_id=target.class_id)

    scores = {}
    for name in ("pre_win", "win", "negative_control"):
        pc = (fixtures / f"{name}.pcdump.txt").read_text(encoding="utf-8")
        src = (fixtures / f"{name}.c").read_text(encoding="utf-8")
        scores[name] = score_candidate_reanchored(
            pc, ref_descs, function=function, class_id=target.class_id,
            order_target=target.order_target, phys_target=target.phys_target,
            cand_source=src,
        )

    # The named pair + its per-candidate order come from order_target.yaml's
    # target_roles (first two persistent roles) and the candidates' ranks.
    pair = tuple(target.target_roles[:2])
    pre_ranks = scores["pre_win"].ranks_by_role or {}
    win_ranks = scores["win"].ranks_by_role or {}
    pre_order = (pre_ranks.get(pair[0], 10**6), pre_ranks.get(pair[1], 10**6))
    win_order = (win_ranks.get(pair[0], 10**6), win_ranks.get(pair[1], 10**6))

    res = evaluate_kill_switch(
        scores=scores, named_pair=pair,
        pre_win_pair_order=pre_order, win_pair_order=win_order,
    )
    res.result_doc_path = _write_result_doc(res, function)
    return res


def _write_result_doc(res: KillSwitchResult, function: str) -> str:
    here = Path(__file__).resolve()
    # tools/melee-agent/src/search/directed/kill_switch.py -> worktree root
    root = here.parents[5]
    out = root / "docs" / "superpowers" / "results" \
        / "2026-06-12-order-distance-kill-switch-result.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    verdict = "PASSED — premise holds; proceed to Plan C" if res.passed \
        else "FIRED — premise REFUTED; STOP. Keep the shipped phys-match " \
             "objective; route the pool to the permuter arm."
    lines = [
        "# Order-distance kill-switch result",
        "",
        f"**Function under test:** {function}",
        f"**Verdict:** {verdict}",
        "",
        "## Assertions",
        f"- (a) same anchored target-role set: {res.assertion_a}",
        f"- (b) strict descent win < pre_win: {res.assertion_b}",
        f"- (c) named pair flips in intended direction: {res.assertion_c}",
        f"- (d) negative control does not descend: {res.assertion_d}",
        "",
        f"**Failure reason:** {res.failure_reason or '(none)'}",
        "",
        "## Detail",
        "",
    ]
    # Render the detail as a 4-space-indented code block (avoids nesting a
    # fenced block inside this module's own source/markdown).
    import json as _json
    for detail_line in _json.dumps(res.detail, indent=2).splitlines():
        lines.append("    " + detail_line)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)
```

- [ ] **Step 4: Run the harness unit tests to verify they pass**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_kill_switch.py -q --no-cov -k "not frozen_fixtures"`
Expected: PASS (6 synthetic assertion tests).

- [ ] **Step 5: Run the live frozen-fixture kill switch + the cardstate secondary witness**

Run the live retrodiction against the frozen bytes (requires the fixtures from T6). This is the DECISIVE step.

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && LIVE_KILLSWITCH=1 python -m pytest tests/search/directed/test_kill_switch.py::test_kill_switch_on_frozen_fixtures -q --no-cov -s 2>&1 | tail -30
```

Expected: either the test PASSES (premise holds — the result doc records PASSED) or it FAILS with `KILL SWITCH FIRED — premise refuted: <reason>` (the result doc records FIRED). Both write `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md`. If the T6 eligibility contingency fired (pre-win base not `directed`), the gating fixture is the cardstate witness; in that case point the harness at a cardstate fixture set (out of this plan's frozen scope) OR record in the result doc that the gating retrodiction is the cardstate decl-chain witness and that the 802427B4 fixture serves only as the negative worked example. Capture the verdict either way.

- [ ] **Step 6: Read the result doc and confirm the verdict is recorded**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && sed -n '1,20p' docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md`
Expected: the verdict line ("PASSED …" or "FIRED …") and the four assertion booleans are present.

- [ ] **Step 7: Commit the harness + result**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/kill_switch.py tools/melee-agent/tests/search/directed/test_kill_switch.py docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md && git commit -m "feat(killswitch): frozen-fixture retrodiction harness + assertions (a)-(d) + result doc (T7)"
```

- [ ] **Step 8: STOP-gate decision**

Per §6c: **if the kill switch fired (any assertion), STOP.** The refutation is in the result doc; keep the shipped phys-match objective and route the pool to the permuter arm. Do NOT proceed to Plan C (loop wiring + pool census). If it passed, Plan C is unblocked. Either way, surface the verdict + the result-doc path to the orchestrator.

---

## Deviations

The following are deliberate deviations from a literal reading of the spec's Plan-A/B task list, each with its reason. None changes a spec contract.

1. **Implementation ORDER within Plan A: T5 is implemented before T4.** The spec lists T4 (scorer order branch) before T5 (generalize the scoring core), but T4's order branch *calls* the generalized `score_candidate_reanchored` from T5. TDD requires the dependency to exist first. Task numbers are preserved (the plan's "Task 5" section precedes its "Task 4" section); spec fidelity is unaffected. Reason: avoids a placeholder/stub in T4 that T5 would replace.

2. **T3 split into a pure classifier (`order_target_derive.py`) + a thin CLI wrapper + a monkeypatched collector seam.** The spec describes T3 as one CLI command. I factored the *classification logic* into a pure, fully-unit-tested function and left the *live tool orchestration* (`_collect_order_target_inputs`) as a seam that tests monkeypatch. Reason: the spec's own §4.2 makes every outcome a named classification that must be exercised deterministically; live mwcc orchestration cannot be unit-tested in CI (serialized full-TU compiles, environment-dependent DLL). The live collector's exact wiring is validated by the pool census (T12, Plan C) and the T6 fixture build, consistent with the spec's note that "the live end-to-end path is exercised at Task 12."

3. **T6 commits fixture SOURCES unconditionally and generates pcdumps + `order_target.yaml` via a committed reproducible script (`build_fixtures.sh`), rather than committing only static frozen bytes.** Reason: pcdump bytes are large, environment-specific, and not reviewable; a committed regeneration script with recorded provenance is the auditable freeze. The `.c` sources and `PROVENANCE.md` (including the eligibility outcome) are committed directly. The frozen `*.pcdump.txt` + `order_target.yaml` are committed as produced by the script so T7's `@slow` test reads frozen bytes. This honors §6c's "extraction + re-verification + freezing, not archaeology" while keeping the freeze reproducible.

4. **The kill-switch harness is split into a pure `evaluate_kill_switch(...)` (assertions over pre-computed scores) + a `run_kill_switch_from_fixtures(...)` (live-bytes driver).** Reason: the four §6c assertions are pure logic and must be unit-tested deterministically without compilation; the live driver reads the frozen pcdumps. This is the same pure-core/live-seam discipline as T3 and matches the spec's intent that the kill switch "scores two FIXED candidate sources through the same scoring core the loop uses" — the shared core is T5's `score_candidate_reanchored`, called by both the scorer (T4) and `run_kill_switch_from_fixtures`.

5. **The scorer order branch in T4 populates the existing `order_distance`/`displacement` meta fields with order semantics but does NOT alter gate/scheduler comparators.** This is not a deviation from the spec (the spec explicitly defers polarity to Plan C T8/T9) but is called out because a reader might expect "order mode" to also flip the gate. For A+B the kill switch reads `CandidateScore.order_distance` directly via the shared core, so the scorer merely *exposing* the order objective is sufficient and correct; flipping the gate before the kill switch passes would be premature.

6. **`order_target.yaml` `phys_target`/`order_target` int-key coercion on YAML load.** The spec's §4.3 schema shows int keys (`{28: 5, 29: 7}`); PyYAML stringifies dict keys on dump. `OrderTarget.load_yaml` coerces them back to int so downstream `int`-keyed lookups (reanchor, colorgraph) work. This is an implementation faithfulness detail, not a schema change.

7. **`8024227C` root-cause attribution updated per ORACLE ROUND 2 erratum (commit `8bd6f8648`).** The frozen spec's §4.4 worked example attributes `8024227C`'s `not_order_class` residual to an "arg-home coalescing root ig56." A later oracle round (verified in `CAMPAIGN-STATE-D1COMPLETION.md` at `8bd6f8648`) **retracted that attribution** — the ig56 coalesce headline was a `match-iter-first [ambiguous]` alignment artifact; the real root is a `void* gobj = arg0;` param-alias **statement-copy emission skew** upstream of select (and ROUND 2 even recovered 94.32→94.80 in C). **The routing VERDICT is unchanged** — `8024227C` still routes `not_order_class` (forcing the order still does not byte-match). The plan therefore (a) reframes the `8024227C`-specific evidence strings/fixtures as "instruction-content/emission divergence upstream of select … ORACLE ROUND 2 erratum, commit 8bd6f8648", (b) generalizes the phys-conflict and class-gate `class_evidence` wording to "node-set divergence upstream of select; confirm attribution" rather than asserting "coalescing", and (c) adds a validation-rationale paragraph to T3 noting the classifier keys on the forced-order byte-verdict, never on attribution — the erratum is positive evidence for that contract (the routing was right while the first attribution was wrong). No contract, schema, task, code-behavior, or test-assertion changes; the generic five-value routing enum and the `not_order_class` verdict for `8024227C` are untouched. Reason: keep the plan's narrative truthful to the latest verified evidence without disturbing the frozen spec or any executable behavior.
