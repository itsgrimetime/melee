# Order-Distance Directed Search — Plans A+B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the order-distance objective core (a proven per-function `OrderTarget` artifact + a derivation/classification CLI + an order-mode scoring path) and a frozen-fixture kill-switch experiment that decides — before any pool campaign — whether the metric retrodicts the known `mnDiagram_802427B4` win.

**Architecture:** This is wiring + data + validation between pieces that already exist (the role-anchored identity layer in `mwcc_debug/`, the Kendall `order_distance` metric, the `force-phys-from-diff` / `match-iter-first` / `dump local --force-iter-first` diagnostic tools, and the directed scorer). Plan A adds a persisted `OrderTarget` YAML schema, a `debug target order-target` derivation pipeline that turns each derivation *outcome* into a named routing classification (with a concrete minimal ≤64 forcing-set search and position-exact verify-application), an order-mode branch in the scorer that bypasses the phys-mode gates entirely in favor of the §3.3 coverage validity (without touching gate/scheduler polarity — that is Plan C), and a generalized reanchored scoring core shared by the scorer and the kill-switch. Plan B freezes pre-win / win / negative-control fixtures for BOTH witnesses — `mnDiagram_802427B4` (commit `a527c0227` and its parent) and the cardstate `fn_803ACD58` decl-chain — via a lock-safe, restore-safe generator script; derives an `OrderTarget` on each base; records which witness gates via `eligibility.json`; and runs four assertions that fire a STOP if the metric cannot retrodict a known win.

**Tech Stack:** Python 3.11, `typer` (CLI), `pyyaml` (artifact persistence — a hard project dependency), `pytest` (`--no-cov` for focused runs), the existing `src.mwcc_debug` role layer and `src.search.directed` scorer.

---

## Conventions for every task in this plan

- **Worktree (pin all commands here):** `/Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign`. Do NOT `cd /Users/mike/code/melee` — that builds the shared main checkout.
- **Test working directory:** `tools/melee-agent`. All `pytest` / `python -m` commands run from there. Because steps cannot persist `cd`, every command is written as a single `cd <worktree>/tools/melee-agent && <cmd>` line.
- **Focused test runs use `--no-cov`** — the repo's default `addopts` enables coverage, which floods output. Example: `python -m pytest tests/search/directed/test_order_target.py -q --no-cov`.
- **All new CLI lands in the PACKAGE copies only:** `tools/melee-agent/src/search/cli/__init__.py` and `tools/melee-agent/src/cli/debug/__init__.py`. NEVER edit the legacy ~1MB siblings `tools/melee-agent/src/search/cli.py` or `tools/melee-agent/src/cli/debug.py` (issue #583 — duplication is filed; new code must not feed it).
- **Plans A+B do NOT touch `gate.py` or `scheduler.py`.** Their higher-is-better polarity is Plan C (T8/T9). The kill-switch (T7) reads order scores directly from the generalized scoring core (T5), never through the gate.
- **Imports inside `src/` use the `src.` package root** (e.g. `from src.search.directed.order_target import OrderTarget`), matching every existing module.
- **Repo-wide lock discipline:** `src/search/adapters.py::_acquire_repo_build_lock` and `src/cli/debug/__init__.py::_acquire_checkdiff_repo_lock` flock the SAME lock file (the adapters docstring says so explicitly). A parent that holds it must run children/in-process re-acquirers with `CHECKDIFF_NO_LOCK=1` (the established `_checkdiff_env_for_locked_child` contract) or it deadlocks itself.
- **`--force-iter-first` position semantics (verified, load-bearing):** the listed igs are popped first by colorgraph **in list order** — the ig at 0-based list index `i` lands at DECISIONS iter position `i` (1-based rank `i+1`). Verified by the existing live test `tests/search/directed/test_order_metric.py::test_live_force_iter_first_distance_is_0` (`--force-iter-first 32,95,40,34,33` → rank40=3, rank33=5). All fixtures in this plan use internally-consistent numbers under this rule (the spec §4.3 example's `force_iter_first: [46,28,29]` + `order_target: {28:5, 29:7}` is an illustrative sketch that violates it — see Deviations #8).
- **checkdiff JSON shape (verified):** `tools/checkdiff.py <fn> --format json` emits `{"function", "match", "classification": {"primary", "reasons", ...}, "fuzzy_match_percent", "target_asm", "current_asm", ...}`. The register-only primaries are `"operand-register-or-offset"` (opcode sequence matches; only operands/registers/labels/offsets differ — checkdiff.py:2163-2166) and `"backend-ceiling"` (its `coloring-rotation` subclass is exactly this pool's signature). Running WITHOUT `--no-build` builds first, so the payload reflects the current TU bytes.

---

## File Structure

New files:
- `tools/melee-agent/src/search/directed/order_target.py` — the `OrderTarget` dataclass (incl. the recorded `named_pair`), the `Routing` enum, YAML load/save, and validation. (T2)
- `tools/melee-agent/tests/search/directed/test_order_target.py` — unit tests for T2.
- `tools/melee-agent/src/mwcc_debug/order_target_derive.py` — the pure derivation/classification helper (`derive_order_target`) the CLI wraps; takes already-collected tool outputs so it is unit-testable without mwcc. (T3)
- `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py` — unit tests for the derivation classifier (T3).
- `tools/melee-agent/tests/cli/test_order_target_cli.py` — CLI wiring + exit-code tests for `debug target order-target` (T3).
- `tools/melee-agent/tests/fixtures/order_distance/generate.py` — the lock-safe, restore-safe fixture generator (replaces any shell-script approach; B8/B9). (T6)
- `tools/melee-agent/tests/fixtures/order_distance/eligibility.json` — machine-readable record of which witness gates (written by `generate.py`). (T6)
- `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/` — frozen: `pre_win.c`, `win.c`, `negative_control.c`, `*.pcdump.txt`, `order_target.yaml`, `PROVENANCE.md`. (T6)
- `tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/` — frozen cardstate witness: `pre_win.c` (=chain step 0), `win.c` (=chain step 1), `negative_control.c`, `chain_2.c`, `chain_3.c`, `*.pcdump.txt`, `order_target.yaml`. (T6)
- `tools/melee-agent/tests/search/directed/test_kill_switch.py` — the kill-switch harness tests + assertions (a)-(d) + the cardstate secondary witness. (T7)
- `tools/melee-agent/src/search/directed/kill_switch.py` — the harness functions the test (and a future CLI) call. (T7)
- `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md` — the result/refutation doc written by T7's run. (T7)

Modified files:
- `tools/melee-agent/src/search/directed/contracts.py:9` — add `objective_mode` + OrderTarget-sourced fields to `DirectedObjective`. (T1)
- `tools/melee-agent/src/search/directed/order_metric.py:204` — generalize `CandidateScore` + `score_candidate_reanchored` to an arbitrary role set; add the §3.3 coverage validity. (T5)
- `tools/melee-agent/src/search/directed/scorer.py:143` — add the `objective_mode == "order"` branch (before ALL phys-mode gates). (T4)
- `tools/melee-agent/src/cli/debug/__init__.py` — register `@target_app.command("order-target")` + the live collector + the forced-dump helper. (T3)

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
        objective_iter_by_original_ig={28: 2, 29: 3}, proof_force_phys={28: 29, 29: 28},
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

A small, persisted, human-auditable YAML artifact (§4.3) plus the routing enum and a validation function. This is pure data plumbing — no mwcc. The schema mirrors §4.3 plus two kill-switch-required fields: `named_pair` (the recorded target-role pair assertion (c) pins — B7) and `named_pair_provenance` (how it was chosen). Validation enforces the structural invariants the derivation pipeline (T3) and the kill switch (T7) rely on: routing is one of the five enum values; when `routing == "directed"` there must be ≥2 `target_roles`, `phys_conflicts` must be empty, every `target_role` must appear in `order_target`, `force_iter_first` must be ≤64 entries, and a non-empty `named_pair` must be exactly 2 igs drawn from `target_roles`.

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
    # Numbers are internally consistent with --force-iter-first semantics:
    # list [46, 28, 29] -> ranks {46: 1, 28: 2, 29: 3} (rank = list index + 1).
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        force_iter_first=[46, 28, 29],
        order_target={28: 2, 29: 3},
        target_roles=[28, 29],
        unscored_roles=[],
        forced_decisions_sha256=["aa", "aa"],
        baseline_source_sha256="bb",
        baseline_pcdump_sha256="cc",
        routing="directed",
        class_evidence="",
        named_pair=[28, 29],
        named_pair_provenance="freeze-time auto-selection",
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
    assert loaded.order_target == {28: 2, 29: 3}
    assert loaded.phys_target == {28: 29, 29: 28}
    assert loaded.named_pair == [28, 29]


def test_load_yaml_tolerates_missing_named_pair(tmp_path):
    # Files written before the named_pair field existed must still load.
    t = _directed_target()
    path = tmp_path / "old.yaml"
    t.save_yaml(path)
    import yaml
    data = yaml.safe_load(path.read_text())
    del data["named_pair"]
    del data["named_pair_provenance"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    loaded = OrderTarget.load_yaml(path)
    assert loaded.named_pair == []
    assert loaded.named_pair_provenance == ""


def test_validate_directed_ok():
    validate_order_target(_directed_target())  # no raise


def test_validate_directed_requires_two_roles():
    with pytest.raises(ValidationError, match="at least 2 target_roles"):
        validate_order_target(_directed_target(
            target_roles=[28], order_target={28: 2}, named_pair=[]))


def test_validate_directed_rejects_conflicts():
    with pytest.raises(ValidationError, match="phys_conflicts"):
        validate_order_target(_directed_target(
            phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))


def test_validate_directed_target_role_must_be_in_order_target():
    with pytest.raises(ValidationError, match="not present in order_target"):
        validate_order_target(_directed_target(target_roles=[28, 99], named_pair=[]))


def test_validate_force_cap():
    with pytest.raises(ValidationError, match="64"):
        validate_order_target(_directed_target(force_iter_first=list(range(65))))


def test_validate_named_pair_must_be_two_target_roles():
    with pytest.raises(ValidationError, match="named_pair"):
        validate_order_target(_directed_target(named_pair=[28, 99]))
    with pytest.raises(ValidationError, match="named_pair"):
        validate_order_target(_directed_target(named_pair=[28]))
    validate_order_target(_directed_target(named_pair=[]))  # empty is allowed


def test_validate_non_directed_skips_role_checks():
    # A not_order_class target need not satisfy the directed invariants.
    t = _directed_target(
        routing="not_order_class", target_roles=[], order_target={},
        named_pair=[], named_pair_provenance="",
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}],
        class_evidence=(
            "instruction-content/emission divergence upstream of select "
            "(8024227C: param-alias statement-copy skew; ORACLE ROUND 2 erratum — "
            "verify with: git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md "
            "| grep -n -A4 'ORACLE ROUND 2')"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_target.py -q --no-cov`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/order_target.py tools/melee-agent/tests/search/directed/test_order_target.py && git commit -m "feat(directed): OrderTarget artifact + Routing enum + named_pair + validation (T2)"
```

---

### Task 3: Derivation pipeline `debug target order-target`

This is the largest task. It orchestrates four existing tools into the §4.2 pipeline and turns every failure mode into a named routing. To keep it testable without mwcc, the classification logic lives in a **pure helper** (`derive_order_target`) that takes the tool *outputs* (already-parsed dicts) and returns an `OrderTarget`. The CLI command is a thin wrapper that calls the real tools and prints/persists the result with routing-mirrored exit codes.

**Why routing keys on the forced-order byte-verdict, not on attribution (validation rationale):** the classifier's routing decision must depend ONLY on whether the forced-ORDER build byte-eliminates the class residual (steps 3-4), never on the *named cause* of a residual. The `8024227C` case proves this is the right contract: ORACLE ROUND 2 retracted the round-1 root-cause attribution (it was a `match-iter-first [ambiguous]` artifact, not arg-home coalescing — the real root was a `void* gobj = arg0;` param-alias statement-copy emission skew), yet the `not_order_class` routing **stood unchanged** because the forced order still did not byte-match. Verify the erratum from any branch with:
`git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md | grep -n -A4 'ORACLE ROUND 2'`
The classifier was correct even though the first-round attribution was wrong — exactly the robustness property a partition needs. Hence `class_evidence` strings are framed as leads to confirm, not proofs.

The pipeline (§4.2), in order, each step a named classification on failure:
1. **Precondition:** register-only checkdiff. The collector runs `tools/checkdiff.py <fn> --format json` **with a build** (never `--no-build` — the object must reflect the current TU bytes). Register-only = `classification.primary` ∈ {`operand-register-or-offset`, `backend-ceiling`} (both have matching opcode sequences; the forced-order class gate at step 4 is the outcome-verified arbiter for anything mis-admitted). Other primaries (e.g. `control-flow-source-shape`, `instruction-sequence`) ⟹ not in this pool (hard error, not a routing).
2. **Phys target + conflict classifier:** the `force-phys-from-diff` derivation (`_derive_force_phys_from_register_diff_lines`) → `{orig_ig: phys}` + `conflicts`. **Any conflict entry ⟹ `not_order_class` immediately** (before spending a forced compile).
3. **Minimal ≤64 forcing set + TRUE forced-ORDER compile (B1):** concrete strategy —
   - (a) *greedy drop of already-correct registers:* anchors are requested ONLY for registers whose force-phys target has `already_target != True` (registers already at their target need no forcing);
   - (b) *natural-prefix preservation:* per-register first-def anchors from the `match-iter-first` matcher, ordered by expected first-def position; the probe window is the natural prefix of at most 64 entries;
   - (c) *outcome-verified probe:* run the window as a `class{N}:ig{M}:iter-first` force-vector through the existing `_run_force_vector_auto_verify` (union probe = forced dump + integrated checkdiff). Union status `match` ⟹ the window is a verified ≤64 eliminating set (chosen). Singleton/prefix diagnostic probes are logged as evidence only — no routing decision reads their internals.
   - `force_cap_blocked` fires ONLY when the anchor list exceeds 64 (the full recommendation cannot even be tested under the cap) AND the 64-entry window does not eliminate the residual. A ≤64 anchor list whose union fails is the step-4 class gate firing (`not_order_class`), not a cap problem.
4. **Verify-application (B2, position-exact) then class-partition gate:** in the chosen window's forced DECISIONS readback, **every forced ig must sit at its forced position** (`rank == list index + 1`) — present-but-elsewhere is a silent misapply ⟹ `unstable_target`. Only then: the forced build must byte-eliminate the targeted class residual (the union probe verdict); if not ⟹ `not_order_class`.
5. **Readback:** `colorgraph_ranks` of the FORCED build → `order_target`; assert forced ig-set ≡ baseline ig-set.
6. **Target-role pruning (§3.3):** keep only roles that round-trip MATCHED on baseline self-reanchor; record failures in `unscored_roles`. <2 survivors ⟹ `unanchorable`.
7. **Determinism (derive twice):** a second forced compile + readback of the SAME chosen set; mismatched DECISIONS-section hash ⟹ `unstable_target`.
8. **Persist** the `OrderTarget`.

**Cache coherence (one flow, no cache reads):** the collector NEVER auto-resolves the cached pcdump. It compiles a fresh baseline pcdump to an explicit temp path (`--no-cache-sync`, leaving the shared cache untouched) and runs checkdiff with a build. Forced dumps never sync the cache anyway (`skip_cache_sync = any_forced or ...` — `cli/debug/__init__.py:17041`).

**Lock discipline (B9):** the collector wraps its whole run in `_acquire_checkdiff_repo_lock(melee_root)`. Its checkdiff/dump children run with `CHECKDIFF_NO_LOCK=1` (`_checkdiff_env_for_locked_child`) so they don't deadlock on the same lock file. When a parent (T6's `generate.py`) already holds the lock and has exported `CHECKDIFF_NO_LOCK=1`, the collector's own acquisition no-ops — the established contract.

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/order_target_derive.py`
- Create: `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py` (register `@target_app.command("order-target")` + collector + forced-dump helper)
- Create: `tools/melee-agent/tests/cli/test_order_target_cli.py`

- [ ] **Step 1: Write the failing tests for the pure classifier**

Create `tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py`:

```python
import pytest

from src.mwcc_debug.order_target_derive import derive_order_target, DeriveInputs
from src.search.directed.order_target import Routing


def _inputs(**over):
    """Build a DeriveInputs whose default tool outputs describe a clean,
    directed, two-role function (mnDiagram_OnFrame-shaped).

    Internally consistent with --force-iter-first semantics: the forced list
    [46, 28, 29] occupies DECISIONS positions 0,1,2 (ranks 1,2,3); unforced
    ig31 follows at rank 4.
    """
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        # Step 1: register-only checkdiff primary.
        checkdiff_primary="operand-register-or-offset",
        # Step 2: force-phys-from-diff.
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        # Step 3: the CHOSEN (minimal, <=64) forcing list + the search verdict.
        force_iter_first=[46, 28, 29],
        # Step 4 verify-application: {forced_ig: 0-based DECISIONS position}.
        applied_positions={46: 0, 28: 1, 29: 2},
        # Step 4: the union probe byte-eliminated the class residual.
        forced_class_clean=True,
        # Step 5: the forced build's COLORGRAPH ranks {ig: rank} (1-based).
        forced_ranks={46: 1, 28: 2, 29: 3, 31: 4},
        baseline_ig_set={46, 28, 29, 31},
        forced_ig_set={46, 28, 29, 31},
        # Step 6: roles that self-reanchor MATCHED on the baseline.
        self_reanchored_roles={28, 29},
        unscored_roles=[{"ig": 31, "reason": "ambiguous_signature"}],
        # Step 7: two forced DECISIONS-section hashes.
        forced_decisions_sha256=["hashA", "hashA"],
        baseline_source_sha256="src1",
        baseline_pcdump_sha256="pc1",
        # B1: True ONLY when anchors > 64 AND no <=64 window eliminated.
        force_cap_exceeded=False,
    )
    base.update(over)
    return DeriveInputs(**base)


def test_clean_two_role_routes_directed():
    t = derive_order_target(_inputs())
    assert t.routing == Routing.DIRECTED.value
    assert t.target_roles == [28, 29]
    assert t.order_target == {28: 2, 29: 3}
    assert t.exit_code() == 0


def test_structural_diff_aborts_before_pool():
    with pytest.raises(ValueError, match="register-only"):
        derive_order_target(_inputs(checkdiff_primary="control-flow-source-shape"))


def test_backend_ceiling_primary_is_admitted():
    # backend-ceiling (coloring-rotation) has matching opcode sequences; the
    # step-4 class gate is the outcome-verified arbiter.
    t = derive_order_target(_inputs(checkdiff_primary="backend-ceiling"))
    assert t.routing == Routing.DIRECTED.value


def test_phys_conflict_routes_not_order_class_early():
    t = derive_order_target(_inputs(
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))
    assert t.routing == Routing.NOT_ORDER_CLASS.value
    assert "ig56" in t.class_evidence or "56" in t.class_evidence
    assert t.exit_code() == 4


def test_force_cap_blocked_only_when_no_minimal_set_found():
    # B1: the classifier routes on the SEARCH verdict, never raw list length —
    # the collector already tried the <=64 window before setting this flag.
    t = derive_order_target(_inputs(force_cap_exceeded=True))
    assert t.routing == Routing.FORCE_CAP_BLOCKED.value
    assert t.exit_code() == 5


def test_oversized_chosen_set_is_force_cap_blocked():
    # Contract guard: a >64 chosen set can never be applied (silent DLL no-op).
    t = derive_order_target(_inputs(force_iter_first=list(range(65))))
    assert t.routing == Routing.FORCE_CAP_BLOCKED.value


def test_force_not_applied_routes_unstable_target():
    # ig29 was forced but absent from the readback (silent no-op).
    t = derive_order_target(_inputs(applied_positions={46: 0, 28: 1}))
    assert t.routing == Routing.UNSTABLE_TARGET.value
    assert t.exit_code() == 6


def test_force_applied_at_wrong_position_routes_unstable_target():
    # B2: present-but-elsewhere is a silent misapply, not an application.
    # ig28 was forced to position 1 but landed at position 3.
    t = derive_order_target(_inputs(applied_positions={46: 0, 28: 3, 29: 2}))
    assert t.routing == Routing.UNSTABLE_TARGET.value
    assert "position" in t.class_evidence


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
force-phys-from-diff, the minimal forcing-set search, two forced dump
readbacks, baseline self-reanchor) and hands them here as a DeriveInputs. This
function applies the ordered classification (each failure mode is a named
routing, never an error) and returns an OrderTarget. Keeping it pure makes the
partition logic unit-testable without any mwcc compilation.

Ordering matters and matches §4.2:
  1. register-only precondition (a structural diff is NOT in this pool -> raise)
  2. phys conflict -> not_order_class (before any forced compile)
  3. minimal-set search exhausted under the 64-cap -> force_cap_blocked
     (the collector sets force_cap_exceeded ONLY after probing the <=64 window;
      a >64 chosen list is a contract guard -> also force_cap_blocked)
  4a. forced ig absent OR at the wrong position -> unstable_target
      (position-exact: the ig at 0-based list index i must sit at DECISIONS
       position i; present-but-elsewhere is a silent misapply)
  4b. forced build did not eliminate the class residual -> not_order_class
  5. forced ig-set != baseline ig-set -> unstable_target
  6. < 2 self-reanchored roles -> unanchorable
  7. derive-twice DECISIONS hashes differ -> unstable_target
  else -> directed

ROUTING KEYS ON THE FORCED-ORDER BYTE-VERDICT, NEVER ON ATTRIBUTION.
class_evidence strings are leads to confirm, not proofs (the 8024227C round-1
"arg-home coalesce" attribution was retracted by ORACLE ROUND 2 while the
not_order_class routing stood; verify:
  git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md | grep -n -A4 'ORACLE ROUND 2').
"""

from __future__ import annotations

from dataclasses import dataclass

from src.search.directed.order_target import FORCE_CAP, OrderTarget, Routing

# checkdiff classification primaries with matching opcode sequences (the
# register-only / FULLNORM-0 admission set). backend-ceiling's coloring-rotation
# subclass is exactly this pool's signature; the step-4 class gate is the
# outcome-verified arbiter for anything mis-admitted.
REGISTER_ONLY_PRIMARIES = {"operand-register-or-offset", "backend-ceiling"}


@dataclass
class DeriveInputs:
    """Collected tool outputs for one function's derivation."""

    function: str
    unit: str
    class_id: int
    checkdiff_primary: str                 # classification["primary"] from checkdiff JSON
    phys_target: dict                      # {orig_ig: desired_phys}
    phys_conflicts: list                   # force-phys-from-diff conflicts
    force_iter_first: list                 # the CHOSEN (<=64) forcing list
    applied_positions: dict                # {forced_ig: 0-based DECISIONS position}
    forced_class_clean: bool               # union probe byte-eliminated the class residual
    forced_ranks: dict                     # {ig: 1-based rank} from the FORCED DECISIONS
    baseline_ig_set: set
    forced_ig_set: set
    self_reanchored_roles: set             # baseline round-trip-MATCHED roles
    unscored_roles: list                   # [{ig, reason}]
    forced_decisions_sha256: list          # two independent forced readbacks
    baseline_source_sha256: str
    baseline_pcdump_sha256: str
    # B1: set by the collector's minimal-set search ONLY when the anchor list
    # exceeded 64 AND the <=64 window did not eliminate the class residual.
    force_cap_exceeded: bool = False


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
    if inp.checkdiff_primary not in REGISTER_ONLY_PRIMARIES:
        raise ValueError(
            f"{inp.function}: checkdiff primary is {inp.checkdiff_primary!r}, "
            f"not register-only ({sorted(REGISTER_ONLY_PRIMARIES)}); "
            f"not in the order-distance pool"
        )

    # Step 2 — phys conflict classifier (BEFORE any forced compile).
    # A phys conflict (same virtual -> >=2 target physregs at different sites)
    # is a NODE-SET-divergence signal: the candidate causes are upstream of
    # select (instruction-content/emission skew, coalescing, VN, or liveness),
    # not the order. The attribution is a lead to confirm, not a proof.
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

    # Step 3 — the 64-entry force cap. Routes ONLY on the collector's
    # minimal-set search verdict (B1), plus a contract guard on the chosen
    # list (a >64 list silently applies NOTHING in the DLL).
    if inp.force_cap_exceeded:
        return _target(
            inp, Routing.FORCE_CAP_BLOCKED,
            class_evidence=(
                f"no <= {FORCE_CAP}-entry forcing set eliminates the class "
                f"residual: the per-register anchor list exceeds the cap and "
                f"the {FORCE_CAP}-entry window probe did not byte-eliminate "
                f"(DLL cap raise is the named fix — a tooling task)"
            ),
        )
    if len(inp.force_iter_first) > FORCE_CAP:
        return _target(
            inp, Routing.FORCE_CAP_BLOCKED,
            class_evidence=(
                f"chosen forcing list has {len(inp.force_iter_first)} entries "
                f"(> {FORCE_CAP}); the DLL silently applies nothing beyond the "
                f"cap, so this set is unusable (collector contract violation)"
            ),
        )

    # Step 4a — verify application, POSITION-EXACT (B2). The ig at 0-based
    # list index i must sit at DECISIONS position i. Present-but-elsewhere is
    # a silent misapply; a force that did not apply must never produce a target.
    misapplied: list[str] = []
    for index, ig in enumerate(inp.force_iter_first):
        actual = inp.applied_positions.get(ig)
        if actual is None:
            misapplied.append(f"ig{ig}: absent from forced readback")
        elif actual != index:
            misapplied.append(
                f"ig{ig}: forced to position {index} but landed at {actual}"
            )
    if misapplied:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            class_evidence=(
                "forced igs did not apply at their forced positions ("
                + "; ".join(misapplied)
                + ") — silent no-op / stale DLL / cap overflow"
            ),
        )

    # Step 4b — class-partition gate.
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
Expected: PASS (13 tests).

- [ ] **Step 5: Commit the pure classifier**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/mwcc_debug/order_target_derive.py tools/melee-agent/tests/mwcc_debug/test_order_target_derive.py && git commit -m "feat(mwcc-debug): pure order-target derivation classifier (T3 core)"
```

- [ ] **Step 6: Write the failing CLI test**

Create `tools/melee-agent/tests/cli/test_order_target_cli.py`. This test invokes the command through Typer's `CliRunner` with the collector monkeypatched so no mwcc runs (the live collector path is exercised at T6's fixture generation and the Plan-C pool census). It pins: directed exit 0 + a written YAML file; not_order_class exit 4 + no YAML written; `--json` emits the full artifact.

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
        checkdiff_primary="operand-register-or-offset",
        phys_target={28: 29, 29: 28}, phys_conflicts=[],
        force_iter_first=[46, 28, 29],
        applied_positions={46: 0, 28: 1, 29: 2},
        forced_class_clean=True,
        forced_ranks={46: 1, 28: 2, 29: 3},
        baseline_ig_set={46, 28, 29}, forced_ig_set={46, 28, 29},
        self_reanchored_roles={28, 29}, unscored_roles=[],
        forced_decisions_sha256=["h", "h"],
        baseline_source_sha256="s", baseline_pcdump_sha256="p",
        force_cap_exceeded=False,
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
    assert loaded.order_target == {28: 2, 29: 3}


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
    assert payload["order_target"] == {"28": 2, "29": 3}
```

- [ ] **Step 7: Run the CLI test to verify it fails**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/cli/test_order_target_cli.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'src.cli.debug' has no attribute '_collect_order_target_inputs'` (and the `order-target` subcommand does not exist).

- [ ] **Step 8: Implement the collector + forced-dump helper + CLI command**

In `tools/melee-agent/src/cli/debug/__init__.py`, add three pieces. Place the two helpers near the other force-vector helpers (search for `def _run_force_vector_auto_verify` ~line 1502 and insert just above it), and register the command in the `target_app` block (search for `@target_app.command(name="match-iter-first")` ~line 13393 and add the new command just before it).

The helpers (live orchestration; monkeypatched out in the CLI tests; the live path is exercised at T6's fixture generation):

```python
def _order_target_forced_dump(
    *,
    tu_c: Path,
    function: str,
    class_id: int,
    force_iter_first: list,
    melee_root: Path,
) -> tuple[dict, set, str]:
    """Run ONE forced-ORDER dump of the CURRENT TU bytes and read it back.

    Returns (ranks {ig: 1-based rank}, ig_set, decisions_sha256). The dump is
    written to an explicit temp path and never touches the shared cache
    (forced dumps skip cache sync by design; --no-cache-sync doubles down).
    Caller must hold (or have disabled via CHECKDIFF_NO_LOCK) the repo lock.
    """
    import hashlib

    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events
    from src.search.directed.order_metric import colorgraph_ranks

    out_path = (
        tu_c.parent
        / f".{function}.order-target.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
    )
    ig_csv = ",".join(str(i) for i in force_iter_first)
    argv = [
        sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu_c),
        "--function", function, "--output", str(out_path), "--no-cache-sync",
        "--force-iter-first", ig_csv,
        "--force-iter-first-class", str(class_id),
        "--force-iter-first-fn", function,
    ]
    proc = subprocess.run(
        argv, cwd=melee_root / "tools" / "melee-agent",
        capture_output=True, text=True, timeout=600,
        env=os.environ.copy(),
    )
    if proc.returncode != 0 or not out_path.exists():
        out_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"forced dump failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[-500:]}"
        )
    text = out_path.read_text(encoding="utf-8")
    out_path.unlink(missing_ok=True)
    ranks = colorgraph_ranks(text, function, class_id=class_id)
    fev = find_function(parse_hook_events(text), function)
    matching = [
        s for s in (fev.colorgraph_sections if fev else [])
        if s.class_id == class_id
    ]
    section = matching[-1] if matching else None
    decisions = section.decisions if section else []
    ig_set = {d.ig_idx for d in decisions}
    sha = hashlib.sha256(
        "\n".join(
            f"{d.iter_idx}:{d.ig_idx}:{d.assigned_reg}" for d in decisions
        ).encode()
    ).hexdigest()
    return ranks, ig_set, sha


def _collect_order_target_inputs(
    *,
    function: str,
    unit: str,
    class_id: int,
    melee_root: Path,
    checkdiff_timeout: float,
):
    """Collect the §4.2 tool outputs for order-target derivation.

    FRESH-EVERYTHING CONTRACT (cache coherence): never auto-resolves the cached
    pcdump and never runs checkdiff --no-build. Everything is derived from the
    CURRENT TU bytes at call time: (1) checkdiff WITH a build; (2) a fresh
    baseline pcdump compiled to an explicit temp path with --no-cache-sync.

    LOCK CONTRACT (B9): wraps the whole run in _acquire_checkdiff_repo_lock
    and runs children with CHECKDIFF_NO_LOCK=1 (_checkdiff_env_for_locked_child)
    so they don't deadlock on the same lock file. Under a parent that already
    holds the lock and exported CHECKDIFF_NO_LOCK=1 (T6 generate.py), the
    acquisition here no-ops — the established contract.

    MINIMAL <=64 FORCING-SET SEARCH (B1), concrete strategy:
      (a) greedy drop of already-correct registers (force-phys targets with
          already_target=True need no forcing);
      (b) natural-prefix preservation: per-register first-def anchors ordered
          by expected first-def position, windowed to the first 64;
      (c) outcome-verified union probe via _run_force_vector_auto_verify
          (forced dump + integrated checkdiff); singleton/prefix probes are
          logged evidence only.
    force_cap_exceeded is True ONLY when len(anchors) > 64 AND the 64-window
    union does not eliminate the residual.

    Monkeypatched out in unit tests; the live path is exercised at T6's
    fixture generation and the Plan-C pool census.
    """
    import hashlib

    from src.mwcc_debug.order_target_derive import (
        REGISTER_ONLY_PRIMARIES,
        DeriveInputs,
    )
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.mwcc_debug.role_reanchor import reanchor_descs
    from src.search.directed.order_metric import colorgraph_ranks
    from src.search.directed.order_target import FORCE_CAP

    tu_c = melee_root / "src" / f"{unit}.c"
    child_env = _checkdiff_env_for_locked_child(disable_fingerprint=False)

    with _acquire_checkdiff_repo_lock(melee_root, label="order-target derivation"):
        # ---- Step 1: FRESH checkdiff (WITH build) --------------------------
        proc = subprocess.run(
            [sys.executable, str(melee_root / "tools" / "checkdiff.py"),
             function, "--format", "json"],
            capture_output=True, text=True,
            timeout=max(checkdiff_timeout, 600),  # the build dominates
            cwd=melee_root, env=child_env,
        )
        checkdiff_payload = json.loads(proc.stdout)
        classification = checkdiff_payload.get("classification") or {}
        checkdiff_primary = (
            classification.get("primary")
            if isinstance(classification, dict) else str(classification)
        ) or "unknown"

        def _inert(**over):
            base = dict(
                function=function, unit=unit, class_id=class_id,
                checkdiff_primary=checkdiff_primary,
                phys_target={}, phys_conflicts=[],
                force_iter_first=[], applied_positions={},
                forced_class_clean=False, forced_ranks={},
                baseline_ig_set=set(), forced_ig_set=set(),
                self_reanchored_roles=set(), unscored_roles=[],
                forced_decisions_sha256=[],
                baseline_source_sha256=hashlib.sha256(
                    tu_c.read_bytes()).hexdigest()[:32],
                baseline_pcdump_sha256="",
                force_cap_exceeded=False,
            )
            base.update(over)
            return DeriveInputs(**base)

        if checkdiff_primary not in REGISTER_ONLY_PRIMARIES:
            # Classifier raises on this (hard error, not a routing).
            return _inert()

        # ---- FRESH baseline pcdump (explicit temp path, never the cache) ---
        baseline_dump = (
            tu_c.parent
            / f".{function}.order-target.baseline.{os.getpid()}.pcdump.txt"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "debug", "dump", "local",
             str(tu_c), "--function", function,
             "--output", str(baseline_dump), "--no-cache-sync"],
            cwd=melee_root / "tools" / "melee-agent",
            capture_output=True, text=True, timeout=600, env=child_env,
        )
        if proc.returncode != 0 or not baseline_dump.exists():
            baseline_dump.unlink(missing_ok=True)
            raise RuntimeError(
                f"baseline dump failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '')[-500:]}"
            )
        pcdump_text = baseline_dump.read_text(encoding="utf-8")
        baseline_dump.unlink(missing_ok=True)

        # ---- Step 2: phys target + conflicts (from the FRESH artifacts) ----
        fns = parse_pcdump(pcdump_text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            raise RuntimeError(f"{function} not found in fresh baseline pcdump")
        pre_pass = fn.last_precolor_pass()
        events_fn = find_function(parse_hook_events(pcdump_text), function)
        target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
        current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
        vector = _derive_force_phys_from_register_diff_lines(
            target_asm, current_asm, pre_pass, events_fn,
        )
        phys_target = {int(k): int(v) for k, v in vector["force_phys"].items()}
        phys_conflicts = list(vector["conflicts"])
        if phys_conflicts:
            # Spec §4.2 step 2: route BEFORE any forced compile is spent.
            return _inert(phys_target=phys_target, phys_conflicts=phys_conflicts)

        # ---- Step 3: per-register anchors + minimal <=64 set search (B1) ---
        mismatched_reg_names: list[str] = []
        for tgt in vector["targets"]:
            if tgt.get("already_target") is True:
                continue
            name = tgt.get("target_reg_name")
            if name and name not in mismatched_reg_names:
                mismatched_reg_names.append(name)
        if not mismatched_reg_names:
            return _inert(phys_target=phys_target)

        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
        asm_fn = asm_extract_function(asm_path.read_text(), function)
        prologue_end = asm_parse_prologue_end(asm_fn.instructions)
        body = asm_fn.instructions[prologue_end:]
        anchor_rows: list[tuple[int, int]] = []  # (expected_pos, ig_idx)
        for reg in _parse_match_iter_first_regs(",".join(mismatched_reg_names)):
            expected_def = asm_find_first_def(
                body, target_reg=reg.number, reg_kind=reg.kind,
            )
            if expected_def is None:
                continue
            pos, expected_ist = expected_def
            match = match_virtual_for_expected_def(
                expected_ist=expected_ist, expected_position=pos,
                pre_pass=pre_pass, reg_kind=reg.kind,
            )
            if match is not None:
                anchor_rows.append((pos, match.ig_idx))
        anchor_rows.sort(key=lambda t: t[0])
        anchors = list(dict.fromkeys(ig for _pos, ig in anchor_rows))

        window = anchors[:FORCE_CAP]
        entries = _parse_force_vector(
            ",".join(f"class{class_id}:ig{ig}:iter-first" for ig in window)
        )
        probe = _run_force_vector_auto_verify(
            src_path=tu_c, function=function, entries=entries,
            melee_root=melee_root, checkdiff_timeout=checkdiff_timeout,
            run_diagnostic_probes=True,  # singleton/prefix evidence, logged only
        )
        forced_class_clean = (probe.get("union") or {}).get("status") == "match"
        force_cap_exceeded = (not forced_class_clean) and len(anchors) > FORCE_CAP
        if force_cap_exceeded:
            return _inert(
                phys_target=phys_target, force_iter_first=window,
                force_cap_exceeded=True,
            )

        # ---- Steps 4-5: forced readback x2 (positions, ranks, igset, sha) --
        forced_ranks, forced_ig_set, sha1 = _order_target_forced_dump(
            tu_c=tu_c, function=function, class_id=class_id,
            force_iter_first=window, melee_root=melee_root,
        )
        applied_positions = {
            ig: forced_ranks[ig] - 1 for ig in window if ig in forced_ranks
        }
        _r2, _s2, sha2 = _order_target_forced_dump(
            tu_c=tu_c, function=function, class_id=class_id,
            force_iter_first=window, melee_root=melee_root,
        )

        # ---- Step 6: baseline self-reanchor over the phys-target roles -----
        baseline_compile = Compile.from_text(
            pcdump_text, function, tu_c.read_text(encoding="utf-8")
        )
        baseline_descs = build_descriptors(baseline_compile, class_id=class_id)
        baseline_ig_set = set(
            colorgraph_ranks(pcdump_text, function, class_id=class_id).keys()
        )
        self_ra = reanchor_descs(
            baseline_descs, baseline_descs, dict(phys_target), class_id=class_id,
        )
        self_reanchored_roles = {orig for _new, orig in self_ra.matched.items()}
        unscored_roles = [
            {"ig": ig, "reason": status}
            for ig, status in self_ra.diagnostics.items()
            if ig in phys_target
        ]

        return DeriveInputs(
            function=function, unit=unit, class_id=class_id,
            checkdiff_primary=checkdiff_primary,
            phys_target=phys_target, phys_conflicts=phys_conflicts,
            force_iter_first=window, applied_positions=applied_positions,
            forced_class_clean=forced_class_clean, forced_ranks=forced_ranks,
            baseline_ig_set=baseline_ig_set, forced_ig_set=forced_ig_set,
            self_reanchored_roles=self_reanchored_roles,
            unscored_roles=unscored_roles,
            forced_decisions_sha256=[sha1, sha2],
            baseline_source_sha256=hashlib.sha256(
                tu_c.read_bytes()).hexdigest()[:32],
            baseline_pcdump_sha256=hashlib.sha256(
                pcdump_text.encode()).hexdigest()[:32],
            force_cap_exceeded=False,
        )
```

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
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/cli/test_order_target_cli.py && git commit -m "feat(cli): debug target order-target command (T3) — collector is mocked-green here; its live path is proven at the T6 fixture generation"
```

---

### Task 5: Generalize `CandidateScore` / `score_candidate_reanchored` to an arbitrary role set

(Implemented before T4 because T4's order branch calls this generalized core. The task is numbered T5 to match the spec.)

Today `CandidateScore` is hardcoded to the pilot's two roles (`rank33`/`rank40`) and `score_candidate_reanchored` defaults to the 9ACC constants. Generalize it to an arbitrary `order_target`/`phys_target` role set, returning `ranks_by_role: {orig_ig: rank}` and a Kendall `order_distance` computed via the role-matched `metric.order_distance`. Add the §3.3 coverage check: a candidate is valid iff EVERY target role round-trip-reanchors (coverage == 1.0 over the target-role set) AND ≥2 roles are anchored; otherwise `valid=False, invalid_reason="target_role_lost"`. Keep the old `rank33`/`rank40` fields and `score_9acc` working so existing tests and callers don't break.

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

In `tools/melee-agent/src/search/directed/order_metric.py`, replace the `CandidateScore` dataclass (lines 204-229) AND the `score_candidate_reanchored` function (lines 232-374) with the following. Keep module imports as-is.

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

- [ ] **Step 4: Flip EXACTLY ONE existing assertion (B5 — the reanchored scorer's metric changed; the standalone metrics did not)**

The generalized `score_candidate_reanchored` now reports **Kendall** distance, while the standalone `order_distance` function, `score_9acc`, and the live tests keep the sum-of-deltas form. **Exactly one existing assertion is affected** — `tests/search/directed/test_order_metric.py:334`, inside `TestScoreCandidateReanchored.test_baseline_identity_stable_order_distance_4` (the only existing test that asserts a non-zero `result.order_distance` from `score_candidate_reanchored`). Rename the test and change that assertion:

```python
    def test_baseline_identity_stable_order_distance_kendall_1(self):
```

and change line 334 from:

```python
        assert result.order_distance == 4
```

to:

```python
        # Kendall: the single (ig33, ig40) pair is inverted vs target -> 1.
        # (The OLD sum-of-deltas form scored this 4; that form still lives in
        # the standalone order_distance/score_9acc, tested separately.)
        assert result.order_distance == 1
```

Do NOT touch: `TestOrderDistance` (~lines 131-168, the standalone sum-of-deltas unit tests, e.g. `test_baseline_distance_is_4`), `TestScoreDataclass.test_baseline_score_shape` (~line 238, asserts `score_9acc(...)` `order_distance == 4`), or the `@slow` live tests (`test_live_baseline_order_distance_is_4` / `test_live_force_iter_first_distance_is_0`) — they all exercise the unchanged standalone metric.

- [ ] **Step 5: Run the full order_metric suite to verify pass + no regressions**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_order_metric.py -q --no-cov`
Expected: PASS (existing tests incl. the renamed one + the 5 new `TestGeneralizedCandidateScore` tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/order_metric.py tools/melee-agent/tests/search/directed/test_order_metric.py && git commit -m "feat(directed): generalize CandidateScore to arbitrary roles + §3.3 coverage validity (T5)"
```

---

### Task 4: Scorer order-mode branch + §3.3 hardened validity

Add the `objective_mode == "order"` branch to `score_directed`. **Placement (B3): the branch sits immediately after the `no_roles` gate and BEFORE every phys-mode gate** — before the compile step, the analyze call, the case-none/abstained checks, the report check, and the generic `coverage_floor=0.5` rejection (scorer.py:190-192). In order mode the §3.3 rules (1.0 target-role coverage, ≥2 anchored — enforced inside the shared T5 core) are THE validity gate; the generic floor and the divergence-case machinery are phys-mode-only. **`displacement` carries the spec's signed-gap diagnostic (`metric.displacement`), never a phys fraction (B6).** Gate/scheduler polarity is untouched (Plan C); for A+B the kill switch reads `CandidateScore.order_distance` directly via the shared core.

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


def _boom(*a, **k):
    raise AssertionError("phys-mode machinery must not run in order mode")


def _order_pipe():
    # Every phys-mode collaborator raises if touched: order mode must branch
    # BEFORE compile/analyze/case/report/coverage (B3).
    return DirectedScorePipeline(
        analyze=_boom,
        compile_from_text=_boom,
        decisions_of=_boom,
        classify=_boom,
    )


def test_order_mode_scores_kendall_and_signed_gap_displacement(tmp_path, monkeypatch):
    from src.search.directed import scorer as scorer_mod
    from src.search.directed.order_metric import CandidateScore

    def fake_score(cand_pcdump_text, ref_descs, **kw):
        # ranks match the target exactly, but phys_matched=0: B6 pins that
        # displacement is the SIGNED-GAP diagnostic (1.0 here), NOT the phys
        # fraction (which would be 0.0).
        return CandidateScore(
            valid=True, invalid_reason=None, ranks_by_role={28: 2, 29: 3},
            order_distance=0, phys_matched=0, coverage=1.0,
        )
    monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", fake_score, raising=False)

    obj = _order_objective({28: 2, 29: 3}, {28: 29, 29: 28})
    out = _order_pipe().score_directed(_art(tmp_path), DirectedScoringCall(obj, _parent(disp=0.0)))
    assert out.status == "ok"
    meta = out.directed_meta
    assert meta.valid is True
    assert meta.order_distance == 0
    assert meta.displacement == pytest.approx(1.0)   # signed-gap, not phys 0/2
    assert meta.case == "order" and meta.label == "order"
    assert out.directed_score == pytest.approx(0.0)  # the Kendall scalar


def test_order_mode_target_role_lost_is_invalid(tmp_path, monkeypatch):
    from src.search.directed import scorer as scorer_mod
    from src.search.directed.order_metric import CandidateScore

    def fake_score(cand_pcdump_text, ref_descs, **kw):
        return CandidateScore(
            valid=False, invalid_reason="target_role_lost", ranks_by_role=None,
            order_distance=None, phys_matched=None, coverage=0.5,
        )
    monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", fake_score, raising=False)

    obj = _order_objective({28: 2, 29: 3}, {28: 29, 29: 28})
    out = _order_pipe().score_directed(_art(tmp_path), DirectedScoringCall(obj, _parent()))
    assert out.status == "invalid"
    assert out.directed_meta.invalid_reason == "target_role_lost"


def test_order_mode_bypasses_generic_coverage_floor_and_analyze(tmp_path, monkeypatch):
    # B3: a candidate the generic 0.5 floor would reject (it never runs) is
    # scored fine when the §3.3 core says valid — and the _boom collaborators
    # prove analyze/compile/case/coverage machinery is structurally bypassed.
    from src.search.directed import scorer as scorer_mod
    from src.search.directed.order_metric import CandidateScore

    def fake_score(cand_pcdump_text, ref_descs, **kw):
        return CandidateScore(
            valid=True, invalid_reason=None, ranks_by_role={28: 3, 29: 2},
            order_distance=1, phys_matched=0, coverage=1.0,
        )
    monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", fake_score, raising=False)

    obj = _order_objective({28: 2, 29: 3}, {28: 29, 29: 28})
    out = _order_pipe().score_directed(_art(tmp_path), DirectedScoringCall(obj, _parent()))
    assert out.status == "ok"
    assert out.directed_meta.order_distance == 1


def test_phys_mode_unchanged_by_order_branch(tmp_path):
    # The default phys path must be byte-identical.
    out = _pipe("B").score_directed(_art(tmp_path), DirectedScoringCall(_objective(), _parent()))
    assert out.status == "ok"
    assert out.directed_meta.case == "B"
    assert hasattr(out.directed_meta, "order_distance")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_scorer.py -q --no-cov -k "order_mode or phys_mode_unchanged"`
Expected: FAIL — the order-mode tests raise `AssertionError: phys-mode machinery must not run in order mode` (the branch doesn't exist, so `_boom` analyze runs).

- [ ] **Step 3: Add the order branch**

In `tools/melee-agent/src/search/directed/scorer.py`, add a module-level import after the existing `from src.search.directed.metric import (...)` block (~line 25):

```python
from src.search.directed.order_metric import score_candidate_reanchored
```

Then, inside `score_directed`, insert the branch **immediately after the roles gate** (after `return self._invalid(art, call, "no_roles")`, ~line 156) and **before** the `# --- compile and analyze ---` section:

```python
        # --- ORDER-MODE BRANCH (order-distance directed search, T4) ----------
        # Placed BEFORE the compile/analyze/case/report/coverage machinery (B3):
        # in order mode the §3.3 rules (1.0 target-role reanchor coverage, >= 2
        # anchored — enforced inside the shared scoring core) are THE validity
        # gate; the divergence-case analysis and the generic coverage_floor=0.5
        # are phys-mode-only. Gate/scheduler polarity is untouched (Plan C).
        if getattr(obj, "objective_mode", "phys") == "order":
            return self._score_order(art, call)

```

Now add the `_score_order` method (and its ref-descs helper) to the `DirectedScorePipeline` class, directly after `score_directed` ends (before `# _attribution`):

```python
    # ------------------------------------------------------------------
    # _score_order — the objective_mode == "order" scoring path.
    # ------------------------------------------------------------------

    def _score_order(self, art: Any, call: DirectedScoringCall) -> Any:
        """Score a candidate against the PROVEN order vector via the shared
        generalized scorer (T5).  Lower order_distance is better; the §3.3
        validity rule (inside the core) rejects candidates that lose a target
        role.

        Field semantics in order mode (B6):
          * order_distance   = role-matched Kendall vs the proven vector;
          * displacement     = metric.displacement — the spec's smooth SIGNED-
                               GAP diagnostic over the same role positions
                               (never the accept/win signal; never a phys
                               fraction);
          * directed_scalar  = the Kendall scalar (float).
        Phys telemetry is NOT folded into any gate field; the CandidateScore
        retains phys_matched for diagnostics read directly by the kill switch.

        Polarity note: the gate and scheduler still read displacement fields
        higher-is-better; flipping that comparator is Plan C (T8/T9). For A+B
        the kill switch reads CandidateScore.order_distance directly, so the
        scorer exposing the objective is sufficient.
        """
        from src.search.directed.metric import displacement as signed_gap_displacement

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

        # B6: displacement carries the SIGNED-GAP DIAGNOSTIC.
        disp = signed_gap_displacement(cs.ranks_by_role or {}, order_target)
        parent_disp = self._parent_displacement_of(parent_state)
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
            case="order",
            label="order",
            order_distance=cs.order_distance,
            displacement=disp,
            displacement_delta=disp - parent_disp,
            reanchor_matched=len(cs.ranks_by_role or {}),
            reanchor_total=len(order_target),
            diagnosis_chars=len("order"),
            applied_mutator=applied_mutator,
            directed_scalar=float(cs.order_distance),
            proof_assignments=None,
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
            iter_order_distance=cs.order_distance,
            iter_displacement=disp,
        )
        return replace(art, directed_score=float(cs.order_distance),
                       directed_meta=meta, status="ok")

    def _order_ref_descs(self, obj: Any) -> dict:
        """Build the baseline identity reference descriptors for order scoring.

        Prefer the objective's pre-built baseline_compile; fall back to building
        from the baseline pcdump path.  One build per candidate is dwarfed by
        the candidate compile, so no caching."""
        from src.mwcc_debug.role_descriptor import Compile, build_descriptors
        bc = obj.baseline_compile
        if bc is not None:
            return build_descriptors(bc, class_id=obj.class_id)
        if obj.baseline_pcdump_path is not None:
            from pathlib import Path
            text = Path(obj.baseline_pcdump_path).read_text(encoding="utf-8")
            compile = Compile.from_text(text, obj.role_target.function, "")
            return build_descriptors(compile, class_id=obj.class_id)
        return {}
```

> Note for the tests' monkeypatch: `_score_order` calls the module-level name `score_candidate_reanchored` imported into `scorer.py`, so `monkeypatch.setattr(scorer_mod, "score_candidate_reanchored", ...)` patches the right reference.

- [ ] **Step 4: Run scorer tests to verify pass + no regressions**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_scorer.py -q --no-cov`
Expected: PASS (all existing phys-path tests + the 4 new order-mode tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/scorer.py tools/melee-agent/tests/search/directed/test_scorer.py && git commit -m "feat(directed): scorer order-mode branch before phys gates + signed-gap displacement (T4)"
```

- [ ] **Step 6: Plan-A regression gate — run the full directed + mwcc_debug suites**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed tests/mwcc_debug/test_order_target_derive.py tests/cli/test_order_target_cli.py -q --no-cov`
Expected: PASS (the full directed test directory plus the two new derivation/CLI suites — no regressions from T1-T5).

---

## Plan B — the kill switch (STOP gate)

### Task 6: Fixture creation for BOTH witnesses + eligibility (the derivation contingency, executable)

Freeze fixtures for **two witnesses**:

1. **`mnDiagram_802427B4`** — pre-win = commit `a527c0227~1` (95.68%), win = `a527c0227` (97.96%, the comma-expr LICM defeat). **The win changes the callee-save count (stmw r20/12-saves → r21/11-saves), so the pre-win base may NOT be derivation-eligible** — §6c's flagged contingency.
2. **`fn_803ACD58` (cardstate decl-chain)** — the contingency fallback AND the secondary witness. Verified chain (each a ONE-LINE decl-order edit to `src/sysdolphin/baselib/hsd_3AA7.c`):
   - chain step 0 = `ffad1f5ed~1` (the base; `387983cd4`'s restructure is already in it),
   - chain step 1 = `ffad1f5ed` (swap: `s32 hdr_plus_icon;`/`s32 i;` → `s32 i;`/`s32 hdr_plus_icon;`, 98.9→99.4),
   - chain step 2 = `f2cf55b2b` (hoist `s32 retries;` to loop-outer scope, 99.4→99.5),
   - chain step 3 = `b7013dc48` (swap `s32 size;`/`s32 retries;`, 99.5→99.7).
   Decl reorders are pure order moves on a stable node set — squarely in-class.

All generation runs through ONE python script, `generate.py` (B8/B9): every TU swap is `try/finally`-restored; the whole run holds the repo build lock and exports `CHECKDIFF_NO_LOCK=1` for children/in-process re-acquirers (the established contract — the build lock IS the checkdiff lock); negative-control edits are EXACT, committed old/new strings verified non-improving at freeze; derivation consumes only fresh artifacts (the T3 collector's fresh-everything contract); the outcome is written to a machine-readable `eligibility.json` that T7 consumes — **no silent unrunnable path**: if NEITHER base derives `directed`, `eligibility.json` records `gating_fixture: null` and T7 hard-stops with an explicit orchestrator report.

**Files:**
- Create: `tools/melee-agent/tests/fixtures/order_distance/generate.py`
- Create: `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/{pre_win.c,win.c,PROVENANCE.md}` (+ generated `negative_control.c`, `*.pcdump.txt`, `order_target.yaml`)
- Create: `tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/{pre_win.c,win.c,chain_2.c,chain_3.c}` (+ generated `negative_control.c`, `*.pcdump.txt`, `order_target.yaml`)
- Create: `tools/melee-agent/tests/fixtures/order_distance/eligibility.json` (generated)

- [ ] **Step 1: Extract the frozen sources for both witnesses**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && mkdir -p tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4 tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58 && git show a527c0227~1:src/melee/mn/mndiagram.c > tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/pre_win.c && git show a527c0227:src/melee/mn/mndiagram.c > tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/win.c && git show ffad1f5ed~1:src/sysdolphin/baselib/hsd_3AA7.c > tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/pre_win.c && git show ffad1f5ed:src/sysdolphin/baselib/hsd_3AA7.c > tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/win.c && git show f2cf55b2b:src/sysdolphin/baselib/hsd_3AA7.c > tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/chain_2.c && git show b7013dc48:src/sysdolphin/baselib/hsd_3AA7.c > tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/chain_3.c && wc -l tools/melee-agent/tests/fixtures/order_distance/*/*.c
```

Expected: six `.c` files written with non-trivial line counts.

- [ ] **Step 2: Write the generator script**

Create `tools/melee-agent/tests/fixtures/order_distance/generate.py`:

```python
#!/usr/bin/env python3
"""Generate the kill-switch frozen artifacts (pcdumps, OrderTargets, negative
controls, eligibility.json) from the committed fixture sources.

Requires a working local mwcc-debug (`melee-agent debug dump doctor` PASSES).
Run from tools/melee-agent:

    python tests/fixtures/order_distance/generate.py

SAFETY CONTRACTS:
  * B8 — every TU swap is try/finally-restored (byte-exact), even on Ctrl-C
    or an exception mid-compile.
  * B9 — the whole run holds the repo-wide build lock
    (src.search.adapters._acquire_repo_build_lock) and exports
    CHECKDIFF_NO_LOCK=1 so children (checkdiff, dump local) and the in-process
    T3 collector — which all re-acquire the SAME lock file — no-op instead of
    deadlocking (the established _checkdiff_env_for_locked_child contract).
    The export happens AFTER our own acquisition (else our own acquisition
    would no-op too).
  * Cache coherence — derivation goes through the T3 collector, whose
    fresh-everything contract compiles its own baseline pcdump and runs
    checkdiff WITH a build; the fixture pcdumps here are likewise written to
    explicit paths with --no-cache-sync. The shared baseline cache is never
    read or written.
  * Negative controls are EXACT committed edits, verified non-improving at
    freeze; a control that improves match% aborts the run loudly.
  * eligibility.json always records the outcome — no silent unrunnable path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tests/fixtures/order_distance
AGENT_ROOT = HERE.parents[2]                    # .../tools/melee-agent
MELEE_ROOT = AGENT_ROOT.parents[1]              # worktree root
sys.path.insert(0, str(AGENT_ROOT))

from src.mwcc_debug.order_target_derive import derive_order_target  # noqa: E402
from src.search.adapters import _acquire_repo_build_lock  # noqa: E402
from src.search.directed.order_metric import score_candidate_reanchored  # noqa: E402
from src.search.directed.order_target import OrderTarget, Routing  # noqa: E402

WITNESSES = [
    {
        "name": "mnDiagram_802427B4",
        "function": "mnDiagram_802427B4",
        "unit": "melee/mn/mndiagram",
        "tu": MELEE_ROOT / "src" / "melee" / "mn" / "mndiagram.c",
        # Exact negative-control candidates (adjacent uninitialized decl swaps
        # inside mnDiagram_802427B4 at a527c0227~1; the first verified
        # non-improving one is used):
        "control_swaps": [
            ("    HSD_Text* text;\n    HSD_Text* row_text;",
             "    HSD_Text* row_text;\n    HSD_Text* text;"),
            ("    f32 x_spacing;\n    f32 y_spacing;",
             "    f32 y_spacing;\n    f32 x_spacing;"),
        ],
        "chain": [],  # no secondary chain for this witness
    },
    {
        "name": "fn_803ACD58",
        "function": "fn_803ACD58",
        "unit": "sysdolphin/baselib/hsd_3AA7",
        "tu": MELEE_ROOT / "src" / "sysdolphin" / "baselib" / "hsd_3AA7.c",
        # chain step 0 (=pre_win) decl block: icon_size; hdr_plus_icon; i;
        # The win lever is the hdr_plus_icon/i pair, so the control swaps the
        # OTHER adjacent pair:
        "control_swaps": [
            ("    s32 icon_size;\n    s32 hdr_plus_icon;",
             "    s32 hdr_plus_icon;\n    s32 icon_size;"),
        ],
        "chain": ["chain_2.c", "chain_3.c"],  # secondary monotone witness
    },
]


@contextmanager
def swapped_tu(tu_path: Path, source_text: str):
    """B8: byte-exact restore on EVERY exit path."""
    original = tu_path.read_bytes()
    try:
        tu_path.write_text(source_text, encoding="utf-8")
        yield
    finally:
        tu_path.write_bytes(original)


def run(argv, cwd, timeout=900):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {' '.join(map(str, argv))}\n"
            f"{(proc.stderr or proc.stdout or '')[-1500:]}"
        )
    return proc


def dump_pcdump(tu: Path, function: str, out: Path) -> None:
    run([sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu),
         "--function", function, "--output", str(out), "--no-cache-sync"],
        cwd=AGENT_ROOT)


def checkdiff_pct(function: str) -> float:
    proc = subprocess.run(
        [sys.executable, str(MELEE_ROOT / "tools" / "checkdiff.py"),
         function, "--format", "json"],
        cwd=MELEE_ROOT, capture_output=True, text=True, timeout=900,
        env=os.environ.copy(),
    )
    payload = json.loads(proc.stdout)
    return float(payload.get("fuzzy_match_percent") or 0.0)


def derive(function: str, unit: str) -> OrderTarget:
    """Run the §4.2 pipeline in-process via the T3 collector (the TU on disk is
    the base being derived — the caller swapped it in)."""
    import src.cli.debug as debugcli
    inputs = debugcli._collect_order_target_inputs(
        function=function, unit=unit, class_id=0,
        melee_root=MELEE_ROOT, checkdiff_timeout=120.0,
    )
    return derive_order_target(inputs)


def choose_named_pair(pre, win, order_target: dict) -> tuple[list, str]:
    """B7: record the pair assertion (c) pins — the first persistent role pair
    inverted in pre_win and correct in win (target direction from the proven
    vector)."""
    if not (pre.valid and win.valid):
        return [], "unavailable: pre/win candidate invalid under the target"
    persistent = sorted(set(pre.ranks_by_role) & set(win.ranks_by_role))
    for a, b in combinations(persistent, 2):
        tdir = order_target[a] < order_target[b]
        pre_dir = pre.ranks_by_role[a] < pre.ranks_by_role[b]
        win_dir = win.ranks_by_role[a] < win.ranks_by_role[b]
        if pre_dir != tdir and win_dir == tdir:
            return [a, b], (
                f"auto-selected at freeze: first persistent pair inverted in "
                f"pre_win and correct in win (target: ig{a} before ig{b})"
            )
    return [], "NO flipping pair among persistent roles — assertion (c) will fire"


def process_witness(w: dict) -> dict:
    wdir = HERE / w["name"]
    fn, unit, tu = w["function"], w["unit"], w["tu"]
    pre_src = (wdir / "pre_win.c").read_text(encoding="utf-8")
    win_src = (wdir / "win.c").read_text(encoding="utf-8")

    # Negative control: first committed exact swap verified non-improving.
    with swapped_tu(tu, pre_src):
        base_pct = checkdiff_pct(fn)
    control_src, control_desc, control_pct = None, None, None
    for old, new in w["control_swaps"]:
        if old not in pre_src:
            continue
        candidate = pre_src.replace(old, new, 1)
        with swapped_tu(tu, candidate):
            pct = checkdiff_pct(fn)
        if pct <= base_pct:
            control_src, control_desc, control_pct = candidate, f"swap: {old!r} -> {new!r}", pct
            break
    if control_src is None:
        raise SystemExit(
            f"[{w['name']}] every candidate control swap improved match% or was "
            f"absent — pick a different adjacent decl pair and re-run (loud abort; "
            f"assertion (d) requires a verified non-improving control)."
        )
    (wdir / "negative_control.c").write_text(control_src, encoding="utf-8")

    # Pcdumps for pre/win/control (+ chain steps).
    sources = {"pre_win": pre_src, "win": win_src, "negative_control": control_src}
    for extra in w["chain"]:
        sources[extra.removesuffix(".c")] = (wdir / extra).read_text(encoding="utf-8")
    for name, src in sources.items():
        with swapped_tu(tu, src):
            dump_pcdump(tu, fn, wdir / f"{name}.pcdump.txt")

    # Derivation on the pre-win base (the eligibility check).
    with swapped_tu(tu, pre_src):
        target = derive(fn, unit)

    record = {
        "routing": target.routing,
        "class_evidence": target.class_evidence,
        "base_match_percent": base_pct,
        "negative_control_edit": control_desc,
        "negative_control_match_percent": control_pct,
    }
    if target.routing != Routing.DIRECTED.value:
        return record

    # Score pre/win against the derived target to record the named pair (B7).
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    pre_pc = (wdir / "pre_win.pcdump.txt").read_text(encoding="utf-8")
    ref_descs = build_descriptors(
        Compile.from_text(pre_pc, fn, pre_src), class_id=0
    )
    def _score(name: str, src_text: str):
        return score_candidate_reanchored(
            (wdir / f"{name}.pcdump.txt").read_text(encoding="utf-8"),
            ref_descs, function=fn, class_id=0,
            order_target=target.order_target, phys_target=target.phys_target,
            cand_source=src_text,
        )
    pair, provenance = choose_named_pair(
        _score("pre_win", pre_src), _score("win", win_src), target.order_target
    )
    target.named_pair = pair
    target.named_pair_provenance = provenance
    target.save_yaml(wdir / "order_target.yaml")
    record["named_pair"] = pair
    record["named_pair_provenance"] = provenance
    return record


def main() -> None:
    results: dict = {}
    with _acquire_repo_build_lock(MELEE_ROOT, label="kill-switch fixture generation"):
        # B9: children + the in-process collector re-acquire the SAME lock
        # file; the env flag makes those acquisitions no-op (established
        # contract). Exported AFTER our own acquisition, removed on exit.
        os.environ["CHECKDIFF_NO_LOCK"] = "1"
        try:
            for w in WITNESSES:
                print(f"=== {w['name']} ===", flush=True)
                results[w["name"]] = process_witness(w)
                print(json.dumps(results[w["name"]], indent=2), flush=True)
        finally:
            os.environ.pop("CHECKDIFF_NO_LOCK", None)

    # Eligibility: the PRIMARY witness gates whenever it derives `directed` —
    # even with an empty named_pair (then T7 FIRES with the precise cause: no
    # persistent pair flips => the win is invisible to role-stable order
    # distance, the §6c assertion (a)/(c) firing at freeze time — it must NOT
    # be dodged by falling back). The cardstate witness is promoted ONLY when
    # the primary base is not derivation-eligible (§6c contingency). Never
    # silent — null means HARD STOP at T7 with an orchestrator report.
    gating = None
    r_802 = results.get("mnDiagram_802427B4") or {}
    r_card = results.get("fn_803ACD58") or {}
    if r_802.get("routing") == Routing.DIRECTED.value:
        gating = "mnDiagram_802427B4"
    elif r_card.get("routing") == Routing.DIRECTED.value:
        gating = "fn_803ACD58"
    eligibility = {
        "gating_fixture": gating,
        "witnesses": results,
        "notes": (
            "gating: mnDiagram_802427B4 whenever it derives directed (an "
            "empty named_pair then FIRES at T7 — the win invisible to "
            "role-stable order distance is a refutation, never dodged); "
            "fn_803ACD58 (pure decl-order chain) is promoted ONLY when the "
            "primary base is not derivation-eligible (§6c contingency). "
            "null gating_fixture => NO derivation-eligible witness: the kill "
            "switch hard-stops and the orchestrator must revisit the "
            "kill-switch function assignment."
        ),
    }
    (HERE / "eligibility.json").write_text(
        json.dumps(eligibility, indent=2), encoding="utf-8"
    )
    print(f"\ngating_fixture: {gating}")
    if gating is None:
        print("NO derivation-eligible witness — T7 will hard-stop with an "
              "orchestrator report. This is a recorded finding, not a silent pass.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the generator (live mwcc; tens of minutes)**

If `debug dump doctor` does not PASS in this worktree, run `python tools/worktree-doctor.py --fix` first.

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m src.cli debug dump doctor 2>&1 | tail -3 && python tests/fixtures/order_distance/generate.py 2>&1 | tail -40
```

Expected: per-witness JSON records, then `gating_fixture: <name-or-None>`; `eligibility.json` + per-witness `negative_control.c`, `*.pcdump.txt`, and (for directed routings) `order_target.yaml` exist. Verify the TUs were restored: `git status --porcelain src/` prints nothing.

- [ ] **Step 4: Write PROVENANCE.md recording the outcome**

Create `tools/melee-agent/tests/fixtures/order_distance/mnDiagram_802427B4/PROVENANCE.md` from this template, filling bracketed values from `eligibility.json`:

```markdown
# Kill-switch fixtures — provenance

## Witness 1: mnDiagram_802427B4
- `pre_win.c` — `src/melee/mn/mndiagram.c` @ `a527c0227~1` (f2d654331), 95.68%.
- `win.c`     — @ `a527c0227` (97.96%; comma-expr LICM defeat:
  `pos.y = (0, mnDiagram_804DBFAC) - HSD_JObjGetTranslationY(j);` + split
  base-pointer `p = sorted; p = p + start;`; stmw r20/12-saves → r21/11-saves —
  the §6c eligibility risk).
- `negative_control.c` — pre_win + [exact swap from eligibility.json];
  freeze-time match% = [X] (<= 95.68 — verified non-improving, assertion (d)).
- Derivation on the pre-win base routed: **[ROUTING]** ([class_evidence]).
- named_pair: [pair] ([named_pair_provenance]).

## Witness 2: fn_803ACD58 (cardstate decl-chain; §6c contingency + secondary witness)
- `pre_win.c` = chain step 0 (`ffad1f5ed~1`); `win.c` = step 1 (`ffad1f5ed`,
  decl swap hdr_plus_icon/i, 98.9→99.4); `chain_2.c` (`f2cf55b2b`, retries
  hoist, →99.5); `chain_3.c` (`b7013dc48`, size/retries swap, →99.7). Each a
  one-line decl-order edit — pure order moves on a stable node set.
- `negative_control.c` — pre_win + icon_size/hdr_plus_icon swap; freeze-time
  match% = [X] (verified non-improving).
- Derivation on chain step 0 routed: **[ROUTING]**.

## Gating decision (eligibility.json)
- gating_fixture = **[NAME or null]**.
- If `mnDiagram_802427B4` routed non-directed: FINDING — the celebrated win is
  (at least partly) a node-set-class win outside this metric's class; the
  cardstate witness is promoted per §6c, and the orchestrator is informed the
  kill-switch function assignment was revisited.
- If BOTH routed non-directed: T7 hard-stops with an orchestrator report —
  never a silent pass.

Regenerate everything with: `cd tools/melee-agent && python tests/fixtures/order_distance/generate.py`
```

- [ ] **Step 5: Commit the fixtures**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/tests/fixtures/order_distance/ && git commit -m "test(killswitch): freeze 802427B4 + cardstate witnesses, exact negative controls, eligibility record (T6)"
```

---

### Task 7: Kill-switch harness + assertions (a)-(d) + secondary witness + result doc

The harness scores the three FIXED candidates of the **gating** witness (selected by `eligibility.json`) through the SAME generalized scoring core (T5) the loop uses. It is mutator-independent by construction. The four assertions (§6c), with the named-pair relation derived **from the scores themselves** (B7 — no disconnected inputs): (a) pre_win and win anchor the SAME target-role set; (b) strict descent `order_distance(win) < order_distance(pre_win)`; (c) the RECORDED `named_pair` from `order_target.yaml` is inverted in pre_win and correct in win (target direction from the proven vector); (d) the negative control does not descend. The cardstate chain is additionally scored as the non-gating monotone secondary witness and reported. Any assertion failing — or no eligible witness existing — is the kill switch firing: the result doc records the refutation/stop and the test fails loudly.

**Files:**
- Create: `tools/melee-agent/src/search/directed/kill_switch.py`
- Create: `tools/melee-agent/tests/search/directed/test_kill_switch.py`
- Create: `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md` (written by the harness run)

- [ ] **Step 1: Write the failing harness unit tests (synthetic, no mwcc)**

Create `tools/melee-agent/tests/search/directed/test_kill_switch.py`:

```python
import os
import pytest

from src.search.directed.kill_switch import evaluate_kill_switch
from src.search.directed.order_metric import CandidateScore


def _score(od, ranks):
    return CandidateScore(
        valid=True, invalid_reason=None, ranks_by_role=ranks,
        order_distance=od, phys_matched=0, coverage=1.0,
    )


# Target: ig21 before ig22 (ranks 5 < 7). Pair order is DERIVED from each
# candidate's ranks_by_role (B7) — there are no separate pair-order inputs.
_TARGET = {21: 5, 22: 7}


def test_all_assertions_pass_when_win_descends():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),            # pair inverted
        "win": _score(0, {21: 5, 22: 7}),                # pair correct, descends
        "negative_control": _score(1, {21: 7, 22: 5}),   # no descent
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is True
    assert (res.assertion_a, res.assertion_b, res.assertion_c, res.assertion_d) == (
        True, True, True, True)


def test_fires_when_win_does_not_descend():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(1, {21: 7, 22: 5}),                # still inverted
        "negative_control": _score(2, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_b is False
    assert "strict descent" in res.failure_reason


def test_fires_when_anchor_sets_differ():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(0, {21: 5, 99: 7}),                # different role anchored
        "negative_control": _score(1, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_a is False


def test_fires_when_negative_control_descends():
    scores = {
        "pre_win": _score(1, {21: 7, 22: 5}),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(0, {21: 5, 22: 7}),   # control improved
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert res.assertion_d is False


def test_fires_when_named_pair_does_not_flip():
    # Three roles: the descent comes from the (22, 23) pair; the NAMED pair
    # (21, 22) was already correct in pre_win -> (c) must fail even though
    # (b) holds. Pins that the descent is the INTENDED relation.
    target = {21: 5, 22: 7, 23: 9}
    scores = {
        "pre_win": _score(1, {21: 5, 22: 7, 23: 6}),     # only (22,23) inverted
        "win": _score(0, {21: 5, 22: 7, 23: 9}),
        "negative_control": _score(1, {21: 5, 22: 7, 23: 6}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=target)
    assert res.passed is False
    assert res.assertion_b is True
    assert res.assertion_c is False


def test_invalid_candidate_fires():
    scores = {
        "pre_win": CandidateScore(False, "target_role_lost", None, None, None, 0.5),
        "win": _score(0, {21: 5, 22: 7}),
        "negative_control": _score(1, {21: 7, 22: 5}),
    }
    res = evaluate_kill_switch(scores=scores, named_pair=(21, 22), order_target=_TARGET)
    assert res.passed is False
    assert "invalid" in res.failure_reason


_LIVE = pytest.mark.skipif(
    not os.environ.get("LIVE_KILLSWITCH"),
    reason="Set LIVE_KILLSWITCH=1 to score the real frozen pcdumps",
)


@pytest.mark.slow
@_LIVE
def test_kill_switch_on_frozen_fixtures():
    """Score the real frozen pcdumps of the GATING witness (eligibility.json)
    against its frozen OrderTarget, write the result doc, and assert the
    verdict. PASS == the premise holds; anything else == STOP (loud)."""
    from pathlib import Path
    from src.search.directed.kill_switch import run_kill_switch_from_fixtures

    # tests/search/directed/test_kill_switch.py -> parents[2] == tests/
    fixtures_root = Path(__file__).resolve().parents[2] / "fixtures" / "order_distance"
    res = run_kill_switch_from_fixtures(fixtures_root)
    assert res.result_doc_path is not None and Path(res.result_doc_path).exists()
    assert res.passed, f"KILL SWITCH FIRED — premise refuted/stopped: {res.failure_reason}"
```

- [ ] **Step 2: Run the harness unit tests to verify they fail**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_kill_switch.py -q --no-cov -k "not frozen_fixtures"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.search.directed.kill_switch'`.

- [ ] **Step 3: Implement the harness**

Create `tools/melee-agent/src/search/directed/kill_switch.py`:

```python
"""Kill switch — frozen-fixture retrodiction of a known win (§6c).

The premise under test: directed order-distance descends toward a forced-ORDER-
proven target and the metric retrodicts a known win. The kill switch scores
THREE FIXED candidate sources (pre_win / win / negative control) of the GATING
witness — selected by tests/fixtures/order_distance/eligibility.json — through
the SAME generalized scoring core the loop uses. It is mutator-independent.

Four assertions (all must hold, else the premise is REFUTED and the campaign
STOPs):
  (a) pre_win and win round-trip-anchor the EXACT same target-role set.
  (b) order_distance(win) < order_distance(pre_win) (both §3.3-valid).
  (c) the RECORDED named_pair (order_target.yaml, with provenance) is inverted
      in pre_win and correct in win — the pair relation is DERIVED from each
      candidate's ranks_by_role and the proven vector's direction (B7).
  (d) order_distance(negative_control) >= order_distance(pre_win).

No eligible witness (eligibility.json gating_fixture == null) is a HARD STOP
with an explicit orchestrator report — never a silent pass. The result is
written to docs/superpowers/results/ on every outcome.
"""

from __future__ import annotations

import json
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
    scores: dict,        # {"pre_win"|"win"|"negative_control": CandidateScore}
    named_pair: tuple,   # (ig_a, ig_b) — the RECORDED pair (order_target.yaml)
    order_target: dict,  # the proven vector {ig: rank}; gives the pair's direction
) -> KillSwitchResult:
    """Apply the four §6c assertions. The pair relation per candidate is
    derived from CandidateScore.ranks_by_role (no disconnected inputs)."""
    pre = scores.get("pre_win")
    win = scores.get("win")
    neg = scores.get("negative_control")

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

    # (c) the RECORDED pair: inverted in pre_win, correct in win, direction
    #     from the proven vector. Derived from ranks_by_role (B7).
    ig_a, ig_b = named_pair
    pair_present = all(
        ig in cs.ranks_by_role for cs in (pre, win) for ig in (ig_a, ig_b)
    ) and ig_a in order_target and ig_b in order_target
    if pair_present:
        target_dir = order_target[ig_a] < order_target[ig_b]
        pre_dir = pre.ranks_by_role[ig_a] < pre.ranks_by_role[ig_b]
        win_dir = win.ranks_by_role[ig_a] < win.ranks_by_role[ig_b]
        c = (pre_dir != target_dir) and (win_dir == target_dir)
    else:
        c = False

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
        reasons.append("assertion (c) failed: the recorded pair "
                       f"{tuple(named_pair)} did not flip in the intended direction "
                       f"(pre_ranks={pre.ranks_by_role} win_ranks={win.ranks_by_role} "
                       f"target={order_target})")
    if not d:
        reasons.append("assertion (d) failed: negative control descended "
                       f"(pre={pre.order_distance} neg={neg.order_distance}) "
                       "— the metric admits false positives")
    return KillSwitchResult(
        passed, a, b, c, d, "; ".join(reasons),
        {
            "pre_win": _cs_dict(pre), "win": _cs_dict(win),
            "negative_control": _cs_dict(neg),
            "named_pair": list(named_pair),
            "order_target": dict(order_target),
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


def _score_fixture(fixtures: Path, target: Any, ref_descs: dict, name: str):
    from src.search.directed.order_metric import score_candidate_reanchored
    pc = (fixtures / f"{name}.pcdump.txt").read_text(encoding="utf-8")
    src = (fixtures / f"{name}.c").read_text(encoding="utf-8")
    return score_candidate_reanchored(
        pc, ref_descs, function=target.function, class_id=target.class_id,
        order_target=target.order_target, phys_target=target.phys_target,
        cand_source=src,
    )


def run_kill_switch_from_fixtures(fixtures_root: Any) -> KillSwitchResult:
    """Live-bytes driver: select the gating witness via eligibility.json, score
    its frozen pcdumps via the shared core, apply the assertions, score the
    cardstate chain as the non-gating secondary witness, and WRITE the result
    doc on every outcome (pass / fire / hard-stop)."""
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.search.directed.order_target import OrderTarget

    root = Path(fixtures_root)
    eligibility = json.loads((root / "eligibility.json").read_text(encoding="utf-8"))
    gating = eligibility.get("gating_fixture")

    if not gating:
        res = KillSwitchResult(
            False, False, False, False, False,
            "HARD STOP: no derivation-eligible witness (eligibility.json "
            "gating_fixture is null) — ORCHESTRATOR ACTION REQUIRED: revisit "
            "the kill-switch function assignment (§6c contingency exhausted)",
            {"eligibility": eligibility},
        )
        res.result_doc_path = _write_result_doc(res, "(none)", eligibility)
        return res

    fixtures = root / gating
    target = OrderTarget.load_yaml(fixtures / "order_target.yaml")
    if len(target.named_pair) != 2:
        res = KillSwitchResult(
            False, False, False, False, False,
            f"KILL SWITCH FIRED: {gating}/order_target.yaml has no recorded "
            f"named_pair ({target.named_pair_provenance or 'no provenance'}). "
            f"Either the T6 generator was not run, or NO persistent role pair "
            f"flips between pre_win and win — the win class is invisible to "
            f"role-stable order distance (the §6c assertion (a)/(c) firing at "
            f"freeze time). ORCHESTRATOR ACTION REQUIRED: this is a refutation "
            f"signal on the gating witness, not a fixture-regeneration errand.",
            {"eligibility": eligibility},
        )
        res.result_doc_path = _write_result_doc(res, target.function, eligibility)
        return res

    pre_pc = (fixtures / "pre_win.pcdump.txt").read_text(encoding="utf-8")
    pre_src = (fixtures / "pre_win.c").read_text(encoding="utf-8")
    ref_descs = build_descriptors(
        Compile.from_text(pre_pc, target.function, pre_src),
        class_id=target.class_id,
    )
    scores = {
        name: _score_fixture(fixtures, target, ref_descs, name)
        for name in ("pre_win", "win", "negative_control")
    }
    res = evaluate_kill_switch(
        scores=scores, named_pair=tuple(target.named_pair),
        order_target=target.order_target,
    )
    res.detail["gating_fixture"] = gating
    res.detail["named_pair_provenance"] = target.named_pair_provenance

    # Secondary witness (non-gating, reported): the cardstate chain scored as
    # a monotone sequence against ITS OWN target, when that target is directed.
    chain_dir = root / "fn_803ACD58"
    chain_yaml = chain_dir / "order_target.yaml"
    if chain_yaml.exists():
        ctarget = OrderTarget.load_yaml(chain_yaml)
        cpre_pc = (chain_dir / "pre_win.pcdump.txt").read_text(encoding="utf-8")
        cpre_src = (chain_dir / "pre_win.c").read_text(encoding="utf-8")
        cref = build_descriptors(
            Compile.from_text(cpre_pc, ctarget.function, cpre_src),
            class_id=ctarget.class_id,
        )
        seq = []
        for name in ("pre_win", "win", "chain_2", "chain_3"):
            if not (chain_dir / f"{name}.pcdump.txt").exists():
                continue
            cs = _score_fixture(chain_dir, ctarget, cref, name)
            seq.append({"step": name, "valid": cs.valid,
                        "order_distance": cs.order_distance})
        ods = [s["order_distance"] for s in seq
               if s["valid"] and s["order_distance"] is not None]
        res.detail["secondary_witness_chain"] = {
            "sequence": seq,
            "non_increasing": all(x >= y for x, y in zip(ods, ods[1:])),
        }
    else:
        res.detail["secondary_witness_chain"] = {
            "sequence": [],
            "note": "cardstate target not directed or not generated — not scored",
        }

    res.result_doc_path = _write_result_doc(res, target.function, eligibility)
    return res


def _write_result_doc(res: KillSwitchResult, function: str, eligibility: dict) -> str:
    here = Path(__file__).resolve()
    # tools/melee-agent/src/search/directed/kill_switch.py -> worktree root
    root = here.parents[5]
    out = root / "docs" / "superpowers" / "results" \
        / "2026-06-12-order-distance-kill-switch-result.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    verdict = "PASSED — premise holds; proceed to Plan C" if res.passed \
        else "FIRED / STOPPED — premise refuted or witness unavailable; STOP. " \
             "Keep the shipped phys-match objective; route the pool to the " \
             "permuter arm."
    lines = [
        "# Order-distance kill-switch result",
        "",
        f"**Gating function:** {function}",
        f"**Gating fixture (eligibility.json):** {eligibility.get('gating_fixture')}",
        f"**Verdict:** {verdict}",
        "",
        "## Assertions",
        f"- (a) same anchored target-role set: {res.assertion_a}",
        f"- (b) strict descent win < pre_win: {res.assertion_b}",
        f"- (c) recorded named pair flips in intended direction: {res.assertion_c}",
        f"- (d) negative control does not descend: {res.assertion_d}",
        "",
        f"**Failure reason:** {res.failure_reason or '(none)'}",
        "",
        "## Detail",
        "",
    ]
    # Render the detail as a 4-space-indented code block (avoids nesting a
    # fenced block inside this module's own source/markdown).
    for detail_line in json.dumps(res.detail, indent=2).splitlines():
        lines.append("    " + detail_line)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)
```

- [ ] **Step 4: Run the harness unit tests to verify they pass**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && python -m pytest tests/search/directed/test_kill_switch.py -q --no-cov -k "not frozen_fixtures"`
Expected: PASS (6 synthetic assertion tests).

- [ ] **Step 5: Run the live frozen-fixture kill switch (the DECISIVE step)**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign/tools/melee-agent && LIVE_KILLSWITCH=1 python -m pytest tests/search/directed/test_kill_switch.py::test_kill_switch_on_frozen_fixtures -q --no-cov -s 2>&1 | tail -30
```

Expected: either PASS (premise holds — the result doc records PASSED, including the secondary-witness chain sequence) or FAIL with `KILL SWITCH FIRED — premise refuted/stopped: <reason>` (the result doc records FIRED/STOPPED — including the hard-stop orchestrator-report path when `gating_fixture` is null or the named pair is unrecorded). Every outcome writes `docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md`.

- [ ] **Step 6: Read the result doc and confirm the verdict is recorded**

Run: `cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && sed -n '1,24p' docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md`
Expected: the gating fixture, the verdict line ("PASSED …" or "FIRED / STOPPED …"), the four assertion booleans, and (below) the secondary-witness chain.

- [ ] **Step 7: Commit the harness + result**

```bash
cd /Users/mike/code/melee/.claude/worktrees/mndiagram-80243434-campaign && git add tools/melee-agent/src/search/directed/kill_switch.py tools/melee-agent/tests/search/directed/test_kill_switch.py docs/superpowers/results/2026-06-12-order-distance-kill-switch-result.md && git commit -m "feat(killswitch): eligibility-gated retrodiction harness + assertions (a)-(d) + chain witness + result doc (T7)"
```

- [ ] **Step 8: STOP-gate decision**

Per §6c: **if the kill switch fired (any assertion, or the hard-stop path), STOP.** The refutation/stop is in the result doc; keep the shipped phys-match objective and route the pool to the permuter arm. Do NOT proceed to Plan C (loop wiring + pool census). If it passed, Plan C is unblocked. Either way, surface the verdict + the result-doc path + (on hard-stop) the orchestrator action to the caller.

---

## Deviations

The following are deliberate deviations from a literal reading of the spec, each with its reason. None changes a spec contract.

1. **Implementation ORDER within Plan A: T5 is implemented before T4.** The spec lists T4 (scorer order branch) before T5 (generalize the scoring core), but T4's order branch *calls* the generalized `score_candidate_reanchored` from T5. TDD requires the dependency to exist first. Task numbers are preserved (the plan's "Task 5" section precedes its "Task 4" section); spec fidelity is unaffected. Reason: avoids a placeholder/stub in T4 that T5 would replace.

2. **T3 split into a pure classifier (`order_target_derive.py`) + a thin CLI wrapper + a monkeypatched collector seam — and the collector has a fresh-everything + lock contract.** The spec describes T3 as one CLI command. The *classification logic* is a pure, fully-unit-tested function; the *live tool orchestration* (`_collect_order_target_inputs`) is a seam that tests monkeypatch. The collector never reads the shared pcdump cache (it compiles its own baseline dump to an explicit temp path) and never runs checkdiff `--no-build` (the object must reflect current TU bytes); it wraps its run in `_acquire_checkdiff_repo_lock` and runs children with `CHECKDIFF_NO_LOCK=1` so a lock-holding parent (T6's generator) composes without deadlock. Reason: §4.2 makes every outcome a named classification that must be exercised deterministically; live mwcc orchestration cannot be unit-tested in CI. The live collector path is exercised at the T6 fixture generation and the Plan-C pool census — and the T3 CLI commit message says so explicitly (honesty about mocked-green).

3. **T6 generates everything through one committed python generator (`generate.py`) with try/finally TU restoration, the repo build lock, exact committed negative-control edits, and a machine-readable `eligibility.json` — and freezes the cardstate witness alongside `802427B4`.** Replaces any shell-swap approach (raw `cp` with no trap — B8) and any out-of-lock compile (B9). The negative controls are exact old/new strings (e.g. the `HSD_Text* text;`/`HSD_Text* row_text;` adjacent swap) verified non-improving at freeze with a loud abort otherwise. The §6c contingency is thereby EXECUTABLE (B4): the cardstate decl-chain (`ffad1f5ed~1` → `ffad1f5ed` → `f2cf55b2b` → `b7013dc48`, each a verified one-line decl move) is frozen, derived, and auto-promoted by `eligibility.json` when — and ONLY when — `802427B4`'s base routes out (non-directed). A `802427B4` base that derives `directed` but yields NO flipping persistent pair stays gating and FIRES at T7 (the win invisible to role-stable order distance is the §6c assertion (a)/(c) refutation, never dodged by fallback); if NEITHER witness derives, T7 hard-stops with an explicit orchestrator report. Never a silent unrunnable path.

4. **The kill-switch harness is split into a pure `evaluate_kill_switch(...)` (assertions over pre-computed scores) + a `run_kill_switch_from_fixtures(...)` (live-bytes, eligibility-gated driver).** The four §6c assertions are pure logic, unit-tested deterministically; the live driver reads the frozen pcdumps of the gating witness, derives the named-pair relation FROM `CandidateScore.ranks_by_role` + the proven vector's direction (no disconnected pair-order inputs — B7), and scores the cardstate chain as the non-gating monotone secondary witness. The shared core is T5's `score_candidate_reanchored`, called by both the scorer (T4) and the driver.

5. **The scorer order branch in T4 bypasses ALL phys-mode gates (compile/analyze/case/report/coverage), not merely the `coverage_floor` rejection.** B3 requires the §3.3 rules to replace the generic floor; this goes further — the divergence-case machinery (case-none/abstained checks, the abstained force-phys fallback, classify_progress) is phys-mode analysis with no role in order scoring, and skipping the analyze call removes a full role-match pass per candidate. The structural bypass is pinned by tests whose phys-mode collaborators raise if touched. `displacement` in order mode carries `metric.displacement` (the spec's signed-gap diagnostic) — never a phys fraction (B6); phys telemetry stays on the `CandidateScore` for diagnostics. Gate/scheduler polarity is untouched (Plan C); the kill switch reads scores directly.

6. **`order_target.yaml` `phys_target`/`order_target` int-key coercion on YAML load.** The spec's §4.3 schema shows int keys; PyYAML stringifies dict keys on dump. `OrderTarget.load_yaml` coerces them back to int so downstream `int`-keyed lookups (reanchor, colorgraph) work. This is an implementation faithfulness detail, not a schema change.

7. **`8024227C` root-cause attribution updated per the ORACLE ROUND 2 erratum.** The frozen spec's §4.4 worked example attributes `8024227C`'s `not_order_class` residual to an "arg-home coalescing root ig56." A later oracle round **retracted that attribution** — the ig56 coalesce headline was a `match-iter-first [ambiguous]` alignment artifact; the real root is a `void* gobj = arg0;` param-alias **statement-copy emission skew** upstream of select (ROUND 2 recovered 94.32→94.80 in C). Verify from any branch: `git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md | grep -n -A4 'ORACLE ROUND 2'`. **The routing VERDICT is unchanged** — `8024227C` still routes `not_order_class` (forcing the order still does not byte-match). The plan therefore frames phys-conflict and class-gate `class_evidence` as "node-set divergence upstream of select; confirm attribution" rather than asserting "coalescing", and T3 carries the validation rationale that routing keys on the forced-order byte-verdict, never attribution — the erratum is positive evidence for that contract.

8. **Fixture numbers follow the VERIFIED `--force-iter-first` semantics, not the spec §4.3 example.** The DLL pops the listed igs first in list order: the ig at 0-based index `i` lands at rank `i+1` (proven by the existing 9ACC live test, `--force-iter-first 32,95,40,34,33` → rank40=3/rank33=5). The spec's §4.3 illustrative example (`force_iter_first: [46,28,29]` with `order_target: {28:5, 29:7}`) violates this; every fixture in this plan uses internally-consistent values (`{28:2, 29:3}`), and the position-exact verify-application (B2) depends on the verified rule.

9. **`OrderTarget` gains `named_pair` + `named_pair_provenance` (schema addition beyond spec §4.3).** Required to make assertion (c) auditable (B7): the pair the kill switch pins is RECORDED in the artifact at freeze time, with provenance describing the automatic selection (first persistent role pair inverted in pre_win and correct in win). Optional with defaults — older YAML files load unchanged; validation only constrains a non-empty pair on directed targets.

10. **The register-only precondition admits `classification.primary ∈ {operand-register-or-offset, backend-ceiling}`.** The spec says "register-only diff (FULLNORM-0)"; checkdiff's actual vocabulary (verified at `tools/checkdiff.py:2163-2166`) marks the opcode-sequence-matching classes with these two primaries (`backend-ceiling`'s `coloring-rotation` subclass IS this pool's signature). A mis-admitted function cannot corrupt a target: the forced-order class gate (step 4) is outcome-verified and routes it `not_order_class`.

11. **`force_cap_blocked` routes on the collector's minimal-set search verdict (`force_cap_exceeded`), never on the raw recommendation length (B1).** The concrete strategy: anchors only for not-already-correct registers (greedy drop of already-correct positions), per-register first-def anchors ordered by expected position (natural-prefix preservation), the ≤64 window probed outcome-verified through the existing `_run_force_vector_auto_verify` union (singleton/prefix probes logged as evidence only — no routing decision reads their payload internals). A ≤64 anchor set whose union fails is the step-4 class gate (`not_order_class`), not a cap problem; `force_cap_exceeded` is set only when the anchor list exceeds 64 AND the 64-window fails. The classifier keeps a >64-chosen-list contract guard (such a list silently applies nothing in the DLL).
