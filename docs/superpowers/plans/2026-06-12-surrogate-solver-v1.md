# Surrogate-as-Solver (inverse register coloring) — v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Plan revision:** rev 2 — incorporates the codex plan review (`/tmp/codex-review-solver-plan.md`: DO-NOT-SHIP, 3 blockers + 7 majors + 1 minor). Every finding is addressed; the finding-by-finding disposition table is at the end of this plan. The single largest change: **Phase 0 now builds the production solver core and runs the calibration gate through the PRODUCTION `solve_coloring` on five REAL frozen fixtures** (codex blocker 2 — rev3 §1.5 requires "the FULL solver (`solve_coloring`, §2 — NOT the filter predicates in isolation)"); what the n≥5 gate blocks is the DRIVER-WIRING phase (CLI, D0 default, suggest conversion, sweep, pilots), exactly as rev3 gates it ("Before `enumerate.py` is wired into a driver/permuter application loop").

**Goal:** Build the node-set/content perturbation **solver** over the already-validated SELECT surrogate (`tools/melee-agent/src/mwcc_debug/tiebreak.py`): a new `node-add` IG-edit primitive, the §1.5 enumeration-time validity filter with PRODUCTION probe-signal derivations, a bounded single+pair enumeration with per-kind eval floors **and a real frontier-pair composition body**, perturbation→C-realization mapping with a fully specified assembly layer, a post-application IG re-extraction gate with STRUCTURAL no-op detection, a ranked worksheet, and the `melee-agent debug solve coloring` CLI. Phase 0 is a BLOCKING calibration gate running the production solver on five permanent real-function fixtures; Phase 1 is the gated driver-facing v1 (D0 catalog before CLI wiring, negative controls N4-N7 with a pair-FOUND assertion, FPR sweep with a strict classifier, pilots, and the `suggest register-tiebreak` thin-caller conversion).

**Architecture:** This is a NEW search layer (`tools/melee-agent/src/search/solver/`) over a PREDICTOR that already exists and is G1-validated. `tiebreak.py` re-implements only MWCC's SELECT phase (`predict_assignments`, `what_if`, `validate_g1`, `build_ig`, `load_ig`). The solver adds (a) `node-add` as a structural edit to the parsed `tiebreak.IG`; (b) the §1.5 filter (L1 interference-survival + L2 (a)/(b)/(c)) as a pre-`predict_assignments` predicate, with `probe.py` deriving the four probe signals from production sources (`explain_virtuals` first-def opcodes, source-object resolution with None→rejected_b, a window-shift residual classifier, the strict-subset use-set survival rule); (c) bounded §2.1 generators + a 200k eval cap with reserved per-kind floors + a production `compose_frontier_pairs` body (apply both perturbations → `predict_assignments` → pair hits, budget-accounted); (d) `realize.py` mapping perturbations to lever-catalog C-moves with source-object resolution, confidence tiering, `tooling_leads` routing, and a tested `assemble_realized` worksheet-assembly layer; (e) `gate.py` re-extracting the real IG after a candidate is written, with no-op detected STRUCTURALLY (IG delta vs baseline, never prediction equality); (f) `worksheet.py` serializing the §7 schema. It REUSES `search/directed/` patterns (the `DirectedMeta.non_actionable` UNATTRIBUTED discipline, the kill-switch dataclass+pure-evaluate+live-driver shape, the lock-safe `generate.py` fixture-freezing pattern) and the force-phys / order-target precondition collector (`_collect_order_target_inputs` → `derive_order_target`).

**Tech Stack:** Python 3.11, `typer` (CLI), `pytest` (`--no-cov` for focused runs; the repo's `addopts` enables coverage which floods output), the existing `src.mwcc_debug.tiebreak` surrogate, `src.mwcc_debug.virtual_attribution` bridge, and `src.search.directed` contracts/order-target collection.

---

## Conventions for every task in this plan

- **Worktree (pin all commands here):** the orchestrator runs this plan inside an isolated worktree. Substitute `<WT>` for the worktree root in every command (e.g. `/Users/mike/code/melee/.claude/worktrees/surrogate-solver`). Do NOT `cd /Users/mike/code/melee` — that builds the shared main checkout and races other agents (CLAUDE.md Build rule).
- **Test working directory:** `<WT>/tools/melee-agent`. All `pytest` / `python -m` commands run from there. Because steps cannot persist `cd`, every command is written as a single `cd <WT>/tools/melee-agent && <cmd>` line.
- **Focused test runs use `--no-cov`** — verified: `tools/melee-agent/pyproject.toml:58` sets `addopts = "--cov=src --cov-report=term-missing --cov-report=html"`.
- **All new CLI lands in the PACKAGE copy only:** `<WT>/tools/melee-agent/src/cli/debug/__init__.py`. NEVER edit the legacy ~1MB sibling `tools/melee-agent/src/cli/debug.py` (issue #583). After any CLI edit, a step verifies the legacy sibling is untouched.
- **Imports inside `src/` use the `src.` package root** (e.g. `from src.search.solver.perturbations import add_node`), matching every existing module.
- **The surrogate is a SELECT-stage model and is NOT modified.** `tiebreak.IG`/`IGNode` (`tiebreak.py:36-52`), `predict_assignments` (`tiebreak.py:116-153`), `validate_g1` (`tiebreak.py:170-185`), `load_ig` (`tiebreak.py:263-276`) are consumed read-only. The solver's `node-add` builds a NEW `IG` from the parsed one; it never edits the surrogate's prediction logic.
- **Repo-wide lock discipline (only the live-build tasks):** `src/search/adapters.py::_acquire_repo_build_lock` and `src/cli/debug/__init__.py::_acquire_checkdiff_repo_lock` (`__init__.py:1868`) flock the SAME lock file. A parent that holds it must run children / in-process re-acquirers with `CHECKDIFF_NO_LOCK=1` (the `_checkdiff_env_for_locked_child` contract, `__init__.py:1857`) or it deadlocks. Only the Task-10 fixture generator, the Task-17 sweep, and the Task-18 pilots touch live mwcc; every other task is mwcc-free.
- **Spec is authoritative.** `docs/superpowers/specs/2026-06-12-surrogate-solver-design.md` (rev 3). Exit codes `0`/`3`/`4` and every schema field name are taken VERBATIM from §7; this plan must not drift them. The one deliberate schema EXTENSION (a `pair_hits` list inside the `pair_escalation` block, needed so N7's "finds the pair" is reportable) is recorded in Deviations.
- **Confidence vocabulary (§7, verbatim):** `surrogate_confidence` is exactly `"high"` or `"proposal"`. `confidence_tier` on a `c_realization` is the lever tier `"a" | "b" | "c"`. Distinct fields; never conflated.
- **Phase-1 gating is MECHANICAL, not textual:** every Phase-1 task begins by running the Phase-1 preflight grep (Task 13 Step 0) that fails closed unless the calibration result doc contains a literal `GATE: PASS` line. Phase-1 tasks MUST NOT be dispatched (including in parallel) before Task 12's checkpoint passes.

---

## Verified substrate (paths/line numbers confirmed 2026-06-12)

| Thing | Location | Verified |
|---|---|---|
| SELECT surrogate `predict_assignments` / `what_if` / `validate_g1` / `build_ig` / `load_ig` | `src/mwcc_debug/tiebreak.py:116/214/170/54/263` | EXISTS |
| `tiebreak.IG` dataclass (`class_id, select_order, nodes, decision_igs`) | `src/mwcc_debug/tiebreak.py:46-52` | EXISTS |
| `tiebreak.IGNode` (`ig_idx, neighbors, precolored, array_size, incomplete, observed_reg`) | `src/mwcc_debug/tiebreak.py:36-44` | EXISTS |
| `parse_register_class` / `register_prefix` / `_register_pools` (FPR pools incl. class 1) | `src/mwcc_debug/tiebreak.py:87/83/96` | EXISTS; FPR pools present, **corpus G1 UNPROVEN** |
| `explain_virtuals(pcdump_text, function, *, virtuals, pairs, source_text, source_file, reg_class)` → `VirtualAttributionReport` | `src/mwcc_debug/virtual_attribution.py:603` | EXISTS |
| `VirtualAttribution` (`virtual, status, class_id, ig_idx, assigned_reg, ..., source: SourceAttribution\|None, interferers, note`) | `src/mwcc_debug/virtual_attribution.py:143-157` | EXISTS; `source` **can be None** |
| `SourceAttribution` (`kind, confidence, name, ..., first_def: InstructionSite\|None, ...`); `InstructionSite.opcode` | `src/mwcc_debug/virtual_attribution.py:96-123` | EXISTS (first-def opcode source for L2(a)) |
| `ColorgraphDecision` (`iter_idx, ig_idx, assigned_reg, n_interferers, interferers`) / `ColorgraphSection` (`class_id, decisions`) | `src/mwcc_debug/colorgraph_parser.py:59/73` | EXISTS |
| `DirectedMeta.non_actionable` UNATTRIBUTED discipline | `src/search/directed/contracts.py:94` | EXISTS |
| Kill-switch shape + lock-safe fixture `generate.py` pattern (`swapped_tu` try/finally, `_acquire_repo_build_lock` + `CHECKDIFF_NO_LOCK=1`) | `src/search/directed/kill_switch.py`; precedent plan T6 | EXISTS (structural template) |
| Precondition collector `_collect_order_target_inputs(*, function, unit, class_id, melee_root, checkdiff_timeout)` → `DeriveInputs` (incl. `checkdiff_primary`, `phys_target`, `phys_conflicts`, `forced_class_clean`) | `src/cli/debug/__init__.py:1565` | EXISTS |
| `derive_order_target` / `REGISTER_ONLY_PRIMARIES` | `src/mwcc_debug/order_target_derive.py` | EXISTS |
| lock helpers `_acquire_checkdiff_repo_lock` / `_checkdiff_env_for_locked_child` | `src/cli/debug/__init__.py:1868/1857` | EXISTS |
| `DEFAULT_MELEE_ROOT`, `_find_unit_for_function`, `_resolve_pcdump_path` | `src/cli/debug/__init__.py` import@33 / `:6395` / `:8578` | EXISTS |
| Typer sub-app pattern (`X_app = typer.Typer(...)`; `debug_app.add_typer(X_app, name="...")`) | `src/cli/debug/__init__.py:1932-1978` | EXISTS; **no `solve_app` today (confirmed grep-empty)** |
| `inspect tiebreak` handler (signature template) | `src/cli/debug/__init__.py:21891` | EXISTS |
| `inspect explain-virtual` handler | `src/cli/debug/__init__.py:22164` | EXISTS |
| Lever catalog + `reverse_compiler_feasibility.md` | agent memory `/Users/mike/.claude/projects/-Users-mike-code-melee/memory/` | EXISTS; **UNTRACKED** (Task 10 snapshots it into the frozen fixtures; Task 13 (D0) promotes the snapshot to tracked `docs/superpowers/lever-catalog/` BEFORE CLI wiring) |

**No `src/search/solver/` or `tests/search/solver/` exists yet** (confirmed). Task 0 creates both.

---

## File Structure

New package `tools/melee-agent/src/search/solver/`:
- `__init__.py` — empty marker. (Task 0)
- `types.py` — `Perturbation` / `PerturbationKind` + schema-exact serializer. (Task 1)
- `perturbations.py` — §1 vocabulary as pure IG-edit functions. (Task 2)
- `validity.py` — the §1.5 filter predicate + `ProbeContext`/`FilterVerdict`. (Task 3)
- `probe.py` — PRODUCTION probe-signal derivations feeding `ProbeContext` (codex blocker 3). (Task 4)
- `enumerate.py` — §2.1 bounded generators, kind normalization, single enumeration with filter tallies + window-order evaluation, **production `compose_frontier_pairs`**, 200k cap with per-kind floors, frontier. (Task 5)
- `worksheet.py` — §7 schema dataclasses + `classify_confidence` + serialize. (Task 6)
- `realize.py` — catalog C-realization + source-object lookup + tiering + **`assemble_realized`** (the tested assembly layer; codex major 10). (Task 7)
- `gate.py` — §3 fidelity gate with STRUCTURAL no-op detection (codex major 9). (Task 8)
- `solve.py` — `solve_coloring` orchestration + exit 0/3/4 incl. the empty-target abstain guard (codex major 7). (Task 9)
- `fpr_sweep.py` — strict sweep classifier + complete live driver (codex major 8). (Task 17)

New tests `tools/melee-agent/tests/search/solver/`:
- `__init__.py`, `test_types.py` (T1), `test_perturbations.py` (T2), `test_validity.py` (T3), `test_probe.py` (T4), `test_enumerate.py` (T5), `test_worksheet.py` (T6), `test_realize.py` (T7), `test_gate.py` (T8), `test_solve.py` (T9), `test_calibration_gate.py` (T11 — the persistent n≥5 regression suite), `test_catalog_dir.py` (T13), `test_cli_solve.py` (T14), `test_negative_controls.py` (T15), `test_suggest_thin_caller.py` (T16), `test_fpr_sweep.py` (T17).

New fixtures `tools/melee-agent/tests/fixtures/solver/`:
- `calibration/generate.py` — the lock-safe live fixture generator (freezes REAL function+IG+target data). (Task 10)
- `calibration/<name>/{base.c, base.pcdump.txt, fixture.json}` for the five fixtures (+ `post_win.c`, `post_win.pcdump.txt` for the two win fixtures). (Task 10)
- `calibration/catalog_snapshot/{node-add,edge-add,edge-remove,order}.json` — the lever-catalog snapshot frozen from the agent memory dir. (Task 10)
- `calibration/FIXTURE_PROVENANCE.md`. (Task 10)
- `n7_pair/{n7_ig.json, PROVENANCE.md}`. (Task 15)

Modified files:
- `src/cli/debug/__init__.py` — define `solve_app`, wire `debug_app.add_typer(solve_app, name="solve")`, register `@solve_app.command("coloring")` (Task 14); convert `suggest register-tiebreak` to a thin caller (Task 16).

New tracked data:
- `docs/superpowers/lever-catalog/*.json` + `README.md` — D0, promoted from the calibration snapshot BEFORE CLI wiring. (Task 13)

New results:
- `docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md` — Phase-0 verdict with a machine-checkable `GATE: PASS|FAIL` line. (Task 12)
- `docs/superpowers/results/2026-06-12-surrogate-solver-fpr-sweep.md`. (Task 17)
- `docs/superpowers/results/2026-06-12-surrogate-solver-pilots.md`. (Task 18)

---

## Phase 0 — production solver core + BLOCKING calibration gate (spec §1.5 / §9 — n≥5)

> **Why the core is built before the gate (codex blocker 2 resolution):** rev3 §1.5 requires the calibration to "run the FULL solver (`solve_coloring`, §2 — NOT the filter predicates in isolation) on a PERMANENT set of FIVE solver-level fixtures ... so the gate exercises enumeration + filter + ranking together rather than unit-testing one predicate." Therefore the production core (Tasks 1-9: types → perturbations → validity → probe → enumerate → worksheet → realize → gate → solve) is built FIRST, mwcc-free and fully unit-tested; Task 10 freezes the five fixtures from REAL functions (live extraction under the lock contract); Task 11 runs the PRODUCTION `solve_coloring` over the frozen artifacts through the production `explain_virtuals`/probe/enumerate/realize paths; Task 12 is the CHECKPOINT. **What the n≥5 gate blocks is Phase 1 — all driver-facing wiring** (`debug solve coloring`, the D0 default catalog, `suggest` conversion, the sweep, the pilots) — exactly rev3's "before `enumerate.py` is wired into a driver/permuter application loop."

### Task 0: Package scaffold

**Files:**
- Create: `tools/melee-agent/src/search/solver/__init__.py`
- Create: `tools/melee-agent/tests/search/solver/__init__.py`
- Create: `tools/melee-agent/tests/fixtures/solver/calibration/.gitkeep`

- [ ] **Step 1: Create the package markers**

```bash
cd <WT>/tools/melee-agent && mkdir -p src/search/solver tests/search/solver tests/fixtures/solver/calibration && : > src/search/solver/__init__.py && : > tests/search/solver/__init__.py && : > tests/fixtures/solver/calibration/.gitkeep && ls src/search/solver tests/search/solver tests/fixtures/solver/calibration
```

Expected: the three paths exist.

- [ ] **Step 2: Verify the package imports clean**

Run: `cd <WT>/tools/melee-agent && python -c "import src.search.solver; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/__init__.py tools/melee-agent/tests/search/solver/__init__.py tools/melee-agent/tests/fixtures/solver/calibration/.gitkeep && git commit -m "chore(solver): package + test scaffold for surrogate-solver (T0)"
```

---

### Task 1: `types.py` — shared `Perturbation` / `PerturbationKind`

**Files:**
- Create: `tools/melee-agent/src/search/solver/types.py`
- Create: `tools/melee-agent/tests/search/solver/test_types.py`

- [ ] **Step 1: Write the failing test**

Create `tools/melee-agent/tests/search/solver/test_types.py`:

```python
from src.search.solver.types import Perturbation, PerturbationKind, serialize_perturbation


def test_perturbation_kinds():
    assert {k.value for k in PerturbationKind} == {
        "node-add", "edge-add", "edge-remove", "order", "coalesce",
    }


def test_node_add_perturbation_shape():
    p = Perturbation(
        kind=PerturbationKind.NODE_ADD, target_ig=41,
        use_set=(42,), new_ig=99, position="after", interfere_original=True,
    )
    assert p.kind is PerturbationKind.NODE_ADD
    assert p.target_ig == 41 and p.use_set == (42,)
    assert p.edge is None and p.order_move is None


def test_edge_perturbation_shape():
    p = Perturbation(kind=PerturbationKind.EDGE_ADD, target_ig=88, edge=(88, 37))
    assert p.edge == (88, 37) and p.use_set is None


def test_order_perturbation_shape():
    p = Perturbation(kind=PerturbationKind.ORDER, target_ig=40,
                     order_move=("before", 33))
    assert p.order_move == ("before", 33)


def test_serialize_matches_schema_fields_only():
    # Spec §7 candidate.perturbation = {kind, target_ig, use_set?, edge?, order_move?}.
    p = Perturbation(PerturbationKind.NODE_ADD, target_ig=41, use_set=(42,),
                     new_ig=99, position="after", interfere_original=True)
    assert serialize_perturbation(p) == {"kind": "node-add", "target_ig": 41,
                                         "use_set": [42]}
    p2 = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    assert serialize_perturbation(p2) == {"kind": "edge-remove", "target_ig": 88,
                                          "edge": [88, 37]}
    p3 = Perturbation(PerturbationKind.ORDER, target_ig=40, order_move=("before", 33))
    assert serialize_perturbation(p3) == {"kind": "order", "target_ig": 40,
                                          "order_move": ["before", 33]}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_types.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.search.solver.types'`.

- [ ] **Step 3: Implement `types.py`**

Create `tools/melee-agent/src/search/solver/types.py`:

```python
"""Shared solver dataclasses (surrogate-as-solver, spec §1/§7).

A Perturbation is the single unit the surrogate scores and realize.py maps to a
C move. `kind` selects which optional fields are meaningful:
  node-add  -> target_ig (the value V being split), use_set, new_ig, position,
               interfere_original
  edge-*    -> edge (a, b)
  order     -> order_move ("before"|"after", anchor_ig)
  coalesce  -> target_ig (experimental; spec §1d, NOT in v1 default kinds)

serialize_perturbation emits EXACTLY the spec §7 schema fields
({kind, target_ig, use_set?, edge?, order_move?}); the internal-only fields
(new_ig/position/interfere_original) are retained in memory for apply/gate use
but never serialized into the worksheet.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class PerturbationKind(enum.Enum):
    NODE_ADD = "node-add"
    EDGE_ADD = "edge-add"
    EDGE_REMOVE = "edge-remove"
    ORDER = "order"
    COALESCE = "coalesce"  # experimental; spec §1d, NOT in v1 default kinds


@dataclass(frozen=True)
class Perturbation:
    kind: PerturbationKind
    target_ig: int
    # node-add only:
    use_set: Optional[tuple] = None
    new_ig: Optional[int] = None
    position: Optional[str] = None            # "before" | "after"
    interfere_original: Optional[bool] = None
    # edge-add / edge-remove only:
    edge: Optional[tuple] = None              # (a, b)
    # order only:
    order_move: Optional[tuple] = None        # ("before"|"after", anchor_ig)


def serialize_perturbation(p: Perturbation) -> dict:
    """Spec §7 candidate.perturbation — schema fields only, Nones omitted."""
    d: dict = {"kind": p.kind.value, "target_ig": p.target_ig}
    if p.use_set is not None:
        d["use_set"] = list(p.use_set)
    if p.edge is not None:
        d["edge"] = list(p.edge)
    if p.order_move is not None:
        d["order_move"] = list(p.order_move)
    return d
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_types.py -q --no-cov`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/types.py tools/melee-agent/tests/search/solver/test_types.py && git commit -m "feat(solver): Perturbation/PerturbationKind + schema-exact serializer (T1)"
```

---

### Task 2: `perturbations.py` — the §1 vocabulary as pure IG-edit functions

Production node-add, edge-add/remove, order, coalesce stub behind a flag. Each is a pure function returning a NEW `tiebreak.IG`; `apply(ig, perturbation)` dispatches.

**Files:**
- Create: `tools/melee-agent/src/search/solver/perturbations.py`
- Create: `tools/melee-agent/tests/search/solver/test_perturbations.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_perturbations.py`:

```python
import pytest

from src.mwcc_debug.tiebreak import IG, IGNode, predict_assignments
from src.search.solver.perturbations import apply, add_node, add_edge, remove_edge, move_order
from src.search.solver.types import Perturbation, PerturbationKind


def _ig():
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42}, {}, 2, False, 30),
        42: IGNode(42, {41}, {}, 1, False, 29),
    }
    return IG(class_id=0, select_order=[40, 41, 42], nodes=nodes,
              decision_igs={40, 41, 42})


def test_add_node_routes_uses_and_overlap_edge():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="after", interfere_original=True)
    assert 99 in ig2.nodes
    assert 42 in ig2.nodes[99].neighbors and 41 in ig2.nodes[99].neighbors
    assert 42 not in ig2.nodes[41].neighbors and 99 in ig2.nodes[41].neighbors
    assert 99 in ig2.nodes[42].neighbors           # symmetric on the routed side
    assert ig2.select_order.index(99) == ig2.select_order.index(41) + 1
    assert 99 not in _ig().nodes                    # pure


def test_add_node_no_interference_omits_vprime_edge():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="before", interfere_original=False)
    assert 41 not in ig2.nodes[99].neighbors
    assert ig2.select_order.index(99) == ig2.select_order.index(41)


def test_add_node_surrogate_predicts_over_perturbed_ig():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="after", interfere_original=True)
    assigns = predict_assignments(ig2)
    assert 99 in assigns and 41 in assigns


def test_add_edge_and_remove_edge_roundtrip():
    base = _ig()
    with_edge = add_edge(base, 40, 42)
    assert 42 in with_edge.nodes[40].neighbors and 40 in with_edge.nodes[42].neighbors
    without = remove_edge(with_edge, 40, 42)
    assert 42 not in without.nodes[40].neighbors


def test_remove_edge_reproduces_v1_remove_88_37():
    # v1 case: remove(88,37) -> ig88 changes register.
    nodes = {
        88: IGNode(88, {37}, {37: 25}, 1, False, 26),
        37: IGNode(37, {88}, {}, 1, False, 25),
    }
    ig = IG(class_id=0, select_order=[37, 88], nodes=nodes, decision_igs={37, 88})
    base = predict_assignments(ig)
    after = predict_assignments(remove_edge(ig, 88, 37))
    assert after[88] != base[88]


def test_move_order_changes_select_position():
    ig2 = move_order(_ig(), target_ig=42, position="before", anchor_ig=40)
    assert ig2.select_order.index(42) < ig2.select_order.index(40)


def test_apply_dispatches_each_kind():
    base = _ig()
    p_node = Perturbation(PerturbationKind.NODE_ADD, target_ig=41, use_set=(42,),
                          new_ig=99, position="after", interfere_original=True)
    assert 99 in apply(base, p_node).nodes
    p_edge = Perturbation(PerturbationKind.EDGE_ADD, target_ig=40, edge=(40, 42))
    assert 42 in apply(base, p_edge).nodes[40].neighbors
    p_rm = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=41, edge=(41, 42))
    assert 42 not in apply(base, p_rm).nodes[41].neighbors
    p_ord = Perturbation(PerturbationKind.ORDER, target_ig=42,
                         order_move=("before", 40))
    assert apply(base, p_ord).select_order.index(42) < 1


def test_apply_coalesce_requires_flag():
    base = _ig()
    p = Perturbation(PerturbationKind.COALESCE, target_ig=41)
    with pytest.raises(ValueError, match="experimental"):
        apply(base, p)
    out = apply(base, p, allow_experimental=True)
    assert isinstance(out, IG)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_perturbations.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `perturbations.py`**

Create `tools/melee-agent/src/search/solver/perturbations.py`:

```python
"""§1 perturbation vocabulary as pure IG-edit functions over tiebreak.IG.

Every function returns a NEW IG (the surrogate is never mutated). apply() is the
dispatcher; node-add is the project's center of gravity, edge and order are the
v1 default companions, coalesce is gated behind a flag (§1d).
"""
from __future__ import annotations

import copy

from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.types import Perturbation, PerturbationKind


def add_node(ig, *, source_ig, new_ig, route_neighbors, position,
             interfere_original):
    """§1a node-add: insert V' (new_ig) copying source_ig, routing a subset of
    its neighbors onto V' and (optionally) adding the V'-V overlap edge."""
    if new_ig in ig.nodes:
        raise ValueError(f"new_ig {new_ig} already present")
    src = ig.nodes[source_ig]
    routed = set(route_neighbors) & set(src.neighbors)
    nodes = copy.deepcopy(ig.nodes)

    vprime_nbrs = set(routed) | ({source_ig} if interfere_original else set())
    vprime_pre = {n: src.precolored[n] for n in routed if n in src.precolored}
    nodes[new_ig] = IGNode(new_ig, vprime_nbrs, vprime_pre, len(vprime_nbrs),
                           False, -1)

    v = nodes[source_ig]
    v.neighbors = (set(v.neighbors) - routed) | ({new_ig} if interfere_original else set())
    v.array_size = len(v.neighbors)
    for n in routed:
        if n in nodes:
            nb = nodes[n]
            nb.neighbors = (set(nb.neighbors) - {source_ig}) | {new_ig}

    order = list(ig.select_order)
    idx = order.index(source_ig)
    order.insert(idx + (1 if position == "after" else 0), new_ig)
    return IG(ig.class_id, order, nodes, set(ig.decision_igs) | {new_ig})


def _with_edge(ig, a, b, *, present):
    nodes = copy.deepcopy(ig.nodes)
    for x, y in ((a, b), (b, a)):
        if x in nodes:
            nbrs = set(nodes[x].neighbors)
            if present:
                nbrs.add(y)
            else:
                nbrs.discard(y)
            nodes[x].neighbors = nbrs
            nodes[x].array_size = len(nbrs)
    return IG(ig.class_id, list(ig.select_order), nodes, set(ig.decision_igs))


def add_edge(ig, a, b):
    return _with_edge(ig, a, b, present=True)


def remove_edge(ig, a, b):
    return _with_edge(ig, a, b, present=False)


def move_order(ig, *, target_ig, position, anchor_ig):
    order = list(ig.select_order)
    if target_ig not in order or anchor_ig not in order:
        return IG(ig.class_id, order, copy.deepcopy(ig.nodes), set(ig.decision_igs))
    order.remove(target_ig)
    i = order.index(anchor_ig)
    order.insert(i + (1 if position == "after" else 0), target_ig)
    return IG(ig.class_id, order, copy.deepcopy(ig.nodes), set(ig.decision_igs))


def _coalesce(ig, target_ig):
    # Experimental (§1d): v1 default never reaches here.
    return IG(ig.class_id, list(ig.select_order), copy.deepcopy(ig.nodes),
              set(ig.decision_igs))


def apply(ig: IG, p: Perturbation, *, allow_experimental: bool = False) -> IG:
    if p.kind is PerturbationKind.NODE_ADD:
        return add_node(ig, source_ig=p.target_ig, new_ig=p.new_ig,
                        route_neighbors=set(p.use_set or ()),
                        position=p.position,
                        interfere_original=bool(p.interfere_original))
    if p.kind is PerturbationKind.EDGE_ADD:
        return add_edge(ig, *p.edge)
    if p.kind is PerturbationKind.EDGE_REMOVE:
        return remove_edge(ig, *p.edge)
    if p.kind is PerturbationKind.ORDER:
        pos, anchor = p.order_move
        return move_order(ig, target_ig=p.target_ig, position=pos, anchor_ig=anchor)
    if p.kind is PerturbationKind.COALESCE:
        if not allow_experimental:
            raise ValueError("coalesce is experimental (spec §1d); pass "
                             "allow_experimental=True / --experimental-kinds coalesce")
        return _coalesce(ig, p.target_ig)
    raise ValueError(f"unknown perturbation kind {p.kind!r}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_perturbations.py -q --no-cov`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/perturbations.py tools/melee-agent/tests/search/solver/test_perturbations.py && git commit -m "feat(solver): §1 perturbation vocabulary as pure IG-edits (T2)"
```

---

### Task 3: `validity.py` — the §1.5 filter predicate

The filter predicate over a `ProbeContext` (the four probe signals). Reason strings match the spec §7 `filter_summary` keys EXACTLY: `rejected_a`, `rejected_b`, `flagged_c`, `rejected_survival`. The PRODUCTION derivation of the four signals is Task 4 (`probe.py`) — this task is the predicate only, unit-tested over explicit contexts (including the ftCo_800DDDE4-shaped admit case, spec §9).

**Files:**
- Create: `tools/melee-agent/src/search/solver/validity.py`
- Create: `tools/melee-agent/tests/search/solver/test_validity.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_validity.py`:

```python
from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import ProbeContext, FilterVerdict, passes_1_5_filter


def _node_add(source_ig=41, use_set=(42,)):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=source_ig,
                        use_set=use_set, new_ig=99, position="after",
                        interfere_original=True)


def _ctx(**over):
    base = dict(
        is_runtime_value=True,                 # L2(a)
        caller_visible_source=True,            # L2(b)
        copy_already_survives=False,           # L2(c)
        original_keeps_use_past_vprime=True,   # L1
    )
    base.update(over)
    return ProbeContext(**base)


def test_admit_ftco_shaped_runtime_caller_visible_interfering():
    v = passes_1_5_filter(_node_add(), _ctx())
    assert v.admit is True and v.reason is None and v.flag is None


def test_reject_a_constant():
    v = passes_1_5_filter(_node_add(), _ctx(is_runtime_value=False))
    assert v.admit is False and v.reason == "rejected_a"


def test_reject_b_intra_inline():
    v = passes_1_5_filter(_node_add(), _ctx(caller_visible_source=False))
    assert v.admit is False and v.reason == "rejected_b"


def test_reject_survival_coalesce_bait():
    v = passes_1_5_filter(_node_add(), _ctx(original_keeps_use_past_vprime=False))
    assert v.admit is False and v.reason == "rejected_survival"


def test_flag_c_window_order():
    # flag-and-quarantine, NOT a hard reject: still evaluated, routed to the
    # window_order bucket, never an apply recommendation (spec §1.5 (c)).
    v = passes_1_5_filter(_node_add(), _ctx(copy_already_survives=True))
    assert v.admit is False and v.flag == "flagged_c" and v.reason is None


def test_non_node_add_is_admitted_unconditionally():
    p = Perturbation(PerturbationKind.EDGE_ADD, target_ig=40, edge=(40, 42))
    v = passes_1_5_filter(p, _ctx(is_runtime_value=False))
    assert v.admit is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_validity.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `validity.py`**

Create `tools/melee-agent/src/search/solver/validity.py`:

```python
"""§1.5 enumeration-time validity filter predicate.

Encodes the two corpus-validated upstream laws over a ProbeContext (derived by
probe.py from production signal sources):

  L1 (survival, 8,888-fn corpus): a same-value copy survives iff the original
     retains >=1 genuine use PAST V''s first use (else it provably coalesces).
  L2 (realizability, 3-site probes):
    (a) RUNTIME value, not a li/lis constant (else rematerialized regardless);
    (b) CALLER-VISIBLE split, not intra-inline (else copy-propagated away);
    (c) genuine pressure/interference, NOT an already-surviving copy whose only
        residual is the callee-save window base -> flag-and-quarantine
        (admit=False, flag="flagged_c"; routed to the window_order bucket and
        STILL surrogate-evaluated — data stays visible, never exit-0/apply).

reject/flag strings == spec §7 filter_summary keys:
  rejected_a, rejected_b, flagged_c, rejected_survival.
Non-node-add kinds bypass the filter (the laws are about node-add).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.search.solver.types import Perturbation, PerturbationKind


@dataclass
class ProbeContext:
    is_runtime_value: bool
    caller_visible_source: bool
    copy_already_survives: bool
    original_keeps_use_past_vprime: bool


@dataclass
class FilterVerdict:
    admit: bool
    reason: Optional[str] = None   # rejected_a | rejected_b | rejected_survival
    flag: Optional[str] = None     # flagged_c (window-order quarantine)


def passes_1_5_filter(p: Perturbation, ctx: ProbeContext) -> FilterVerdict:
    if p.kind is not PerturbationKind.NODE_ADD:
        return FilterVerdict(admit=True)
    if not ctx.is_runtime_value:
        return FilterVerdict(admit=False, reason="rejected_a")
    if not ctx.caller_visible_source:
        return FilterVerdict(admit=False, reason="rejected_b")
    if not ctx.original_keeps_use_past_vprime:
        return FilterVerdict(admit=False, reason="rejected_survival")
    if ctx.copy_already_survives:
        return FilterVerdict(admit=False, flag="flagged_c")
    return FilterVerdict(admit=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_validity.py -q --no-cov`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/validity.py tools/melee-agent/tests/search/solver/test_validity.py && git commit -m "feat(solver): §1.5 validity predicate — L1 survival + L2 a/b/c, schema-keyed reasons (T3)"
```

---

### Task 4: `probe.py` — PRODUCTION probe-signal derivations (codex blocker 3)

The four `ProbeContext` signals derived from production sources, shared by the calibration gate (Task 11), the CLI live adapter (Task 14), and unit tests:
- **`is_runtime_value` (L2(a)):** from V's first-def opcode (`explain_virtuals` → `VirtualAttribution.source.first_def.opcode`, `virtual_attribution.py:96-123`). `li`/`lis`-defined → constant → False. Unknown/absent first-def → True (the spec's check rejects only PROVEN li/lis-defined constants).
- **`caller_visible_source` (L2(b)):** the resolved source object is not None. `explain_virtuals`' `source` can be None (intra-inline / unresolvable) → False → `rejected_b` (codex ruling: unresolved → rejected_b).
- **`copy_already_survives` (L2(c)):** the function-level window-shift residual classifier `is_window_order_residual(ig, phys_target)`: every target ig's observed AND desired register is a callee-save AND the observed−desired deltas form a single nonzero constant (a uniform allocation-window shift, the CreateStatRow r22-vs-r21 signature). Applied to all node-add candidates of a window-residual function so ALL surviving hits are window-flagged → exit-4 `window-order` (spec §1.5 (c)). A stated heuristic; the Task-11 gate validates it on the flag_c fixture.
- **`original_keeps_use_past_vprime` (L1):** the strict-subset rule — the routed use-set is a PROPER subset of V's modelled uses (neighbor-set proxy); routing ALL uses through V' is coalesce-bait → `rejected_survival`.

**Files:**
- Create: `tools/melee-agent/src/search/solver/probe.py`
- Create: `tools/melee-agent/tests/search/solver/test_probe.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_probe.py`:

```python
from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.probe import (
    derive_probe_context, first_def_opcode_of, is_window_order_residual,
    source_object_of,
)
from src.search.solver.types import Perturbation, PerturbationKind


def _ig(observed_42=22):
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42, 43}, {}, 3, False, 30),
        42: IGNode(42, {41}, {}, 1, False, observed_42),
        43: IGNode(43, {41}, {}, 1, False, 20),
    }
    return IG(class_id=0, select_order=[40, 41, 42, 43], nodes=nodes,
              decision_igs={40, 41, 42, 43})


def _node_add(target=41, use_set=(42,)):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=target,
                        use_set=use_set, new_ig=99, position="after",
                        interfere_original=True)


# --- L2(a): runtime vs li/lis constant ---
def test_constant_li_defined_is_not_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="li",
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is False


def test_lis_defined_is_not_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lis",
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is False


def test_unknown_first_def_is_admitted_as_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode=None,
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is True


# --- L2(b): caller visibility from the resolved source object ---
def test_no_source_object_is_not_caller_visible():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lwz",
                               source_object=None, window_residual=False)
    assert ctx.caller_visible_source is False


# --- L2(c): window-shift residual classifier ---
def test_uniform_callee_save_shift_is_window_residual():
    # observed r22/r20 vs desired r21/r19: uniform +1 shift on callee-saves.
    assert is_window_order_residual(_ig(observed_42=22), {42: 21, 43: 19}) is True


def test_mixed_deltas_are_not_window_residual():
    # 42: 22->21 (+1) but 43: 20->17 (+3): not a uniform shift.
    assert is_window_order_residual(_ig(observed_42=22), {42: 21, 43: 17}) is False


def test_volatile_target_is_not_window_residual():
    # desired r3 is a volatile, not a callee-save window member.
    assert is_window_order_residual(_ig(observed_42=4), {42: 3}) is False


def test_window_residual_flags_copy_already_survives():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=True)
    assert ctx.copy_already_survives is True


# --- L1: strict-subset survival rule ---
def test_routing_all_uses_is_coalesce_bait():
    p = _node_add(target=41, use_set=(40, 42, 43))   # ALL of 41's neighbors
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=False)
    assert ctx.original_keeps_use_past_vprime is False


def test_routing_proper_subset_keeps_a_use():
    p = _node_add(target=41, use_set=(42,))
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=False)
    assert ctx.original_keeps_use_past_vprime is True


# --- report accessors: explain_virtuals report -> name / first-def opcode ---
def test_report_accessors_handle_none_and_named():
    class _FD:
        opcode = "li"
    class _Src:
        name = "row_text"
        expression = None
        first_def = _FD()
    class _VA:
        def __init__(self, ig_idx, source):
            self.ig_idx = ig_idx
            self.source = source
    class _Report:
        virtuals = (_VA(41, _Src()), _VA(50, None))

    assert source_object_of(_Report(), 41) == "row_text"
    assert source_object_of(_Report(), 50) is None
    assert source_object_of(_Report(), 999) is None
    assert first_def_opcode_of(_Report(), 41) == "li"
    assert first_def_opcode_of(_Report(), 50) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_probe.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `probe.py`**

Create `tools/melee-agent/src/search/solver/probe.py`:

```python
"""PRODUCTION probe-signal derivations feeding the §1.5 ProbeContext.

Shared by the calibration gate (frozen pcdump+source artifacts), the CLI live
adapter, and unit tests — ONE derivation path so the filter is never fed
hardcoded-permissive signals (codex blocker 3).

Signal sources:
  is_runtime_value (L2(a))   : V's first-def opcode from explain_virtuals'
                               SourceAttribution.first_def. li/lis -> constant.
                               Unknown -> True (the spec rejects only PROVEN
                               li/lis-defined constants).
  caller_visible_source (b)  : resolved source object is not None (explain-
                               virtual's source can be None: intra-inline /
                               unresolvable -> rejected_b).
  copy_already_survives (c)  : function-level window-shift residual — every
                               phys_target entry maps callee-save -> callee-save
                               with ONE uniform nonzero delta (the CreateStatRow
                               r22-vs-r21 signature). Heuristic, stated as such;
                               the Task-11 calibration gate validates it on the
                               flag_c fixture.
  original_keeps_use_past_vprime (L1): the routed use-set is a PROPER subset of
                               V's modelled uses (neighbor-set proxy); routing
                               ALL uses is coalesce-bait.
"""
from __future__ import annotations

from typing import Optional

from src.mwcc_debug.tiebreak import IG
from src.search.solver.types import Perturbation
from src.search.solver.validity import ProbeContext

_CONST_DEF_OPCODES = {"li", "lis"}
_GPR_CALLEE_SAVES = set(range(13, 32))   # r13-r31
_FPR_CALLEE_SAVES = set(range(14, 32))   # f14-f31


def _callee_saves(class_id: int) -> set:
    return _FPR_CALLEE_SAVES if class_id == 1 else _GPR_CALLEE_SAVES


def is_window_order_residual(ig: IG, phys_target: dict) -> bool:
    """True when the residual is a uniform callee-save window shift: every
    target ig's observed AND desired register is a callee-save, and all
    observed-desired deltas equal one nonzero constant."""
    if not phys_target:
        return False
    saves = _callee_saves(ig.class_id)
    deltas = set()
    for ig_idx, desired in phys_target.items():
        node = ig.nodes.get(int(ig_idx))
        if node is None:
            return False
        observed = node.observed_reg
        if observed not in saves or desired not in saves:
            return False
        deltas.add(observed - desired)
    return len(deltas) == 1 and 0 not in deltas


def source_object_of(report, ig_idx: int) -> Optional[str]:
    """Resolved source object for ig_idx from a VirtualAttributionReport.
    None when the attribution has no source (drives rejected_b / tooling_leads)."""
    for va in getattr(report, "virtuals", ()):
        if getattr(va, "ig_idx", None) == ig_idx:
            src = getattr(va, "source", None)
            if src is None:
                return None
            return getattr(src, "name", None) or getattr(src, "expression", None)
    return None


def first_def_opcode_of(report, ig_idx: int) -> Optional[str]:
    """V's first-def opcode from the same report (None when absent)."""
    for va in getattr(report, "virtuals", ()):
        if getattr(va, "ig_idx", None) == ig_idx:
            src = getattr(va, "source", None)
            fd = getattr(src, "first_def", None) if src is not None else None
            return getattr(fd, "opcode", None) if fd is not None else None
    return None


def derive_probe_context(p: Perturbation, ig: IG, *,
                         first_def_opcode: Optional[str],
                         source_object: Optional[str],
                         window_residual: bool) -> ProbeContext:
    node = ig.nodes.get(p.target_ig)
    uses = set(node.neighbors) if node is not None else set()
    routed = set(p.use_set or ())
    keeps = bool(uses) and routed < uses          # PROPER subset (L1)
    runtime = True
    if first_def_opcode:
        runtime = first_def_opcode.strip().lower() not in _CONST_DEF_OPCODES
    return ProbeContext(
        is_runtime_value=runtime,
        caller_visible_source=source_object is not None,
        copy_already_survives=window_residual,
        original_keeps_use_past_vprime=keeps,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_probe.py -q --no-cov`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/probe.py tools/melee-agent/tests/search/solver/test_probe.py && git commit -m "feat(solver): probe.py — production §1.5 signal derivations (first-def/source/window-shift/strict-subset) (T4)"
```

---

### Task 5: `enumerate.py` — bounded generators, kind normalization, filter tallies, PRODUCTION pair composition

The §2.1 bounded generators (`implicated_nodes` 1-hop with widen-to-2-hop cap 64, `use_set_family` ×4, `insertion_positions` ×2), kind normalization (`edge` expands to `edge-add`+`edge-remove` — codex major 6), single enumeration that TALLIES filter verdicts (the `filter_summary` counts) and EVALUATES window-flagged candidates into a separate bucket (spec §1.5 (c): "window-order candidates ARE still enumerated — data stays visible"), the 200k cap with reserved per-kind floors, **and the production `compose_frontier_pairs` body** (codex blocker 1): for each unordered frontier pair, apply BOTH perturbations, run `predict_assignments`, record FULL pair hits, charge evals against the remaining global budget. Pairs fire when NO actionable single exists (finding 3), NOT on zero hits.

**Files:**
- Create: `tools/melee-agent/src/search/solver/enumerate.py`
- Create: `tools/melee-agent/tests/search/solver/test_enumerate.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_enumerate.py`:

```python
from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.enumerate import (
    EnumConfig, EnumResult, compose_frontier_pairs, enumerate_single,
    enumerate_with_escalation, implicated_nodes, insertion_positions,
    normalize_kinds, use_set_family,
)
from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import FilterVerdict


def _ig():
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42}, {}, 2, False, 30),
        42: IGNode(42, {41, 43}, {}, 2, False, 29),
        43: IGNode(43, {42}, {}, 1, False, 28),
    }
    return IG(class_id=0, select_order=[40, 41, 42, 43], nodes=nodes,
              decision_igs={40, 41, 42, 43})


def _pair_only_ig():
    """Verified pair-only construction: 50 and 51 each blocked from r3 by BOTH
    40 and 41 (each holding r3, forced off r0 by a machine-reg-0 interferer);
    no single perturbation meets BOTH targets {50:3, 51:3}; the pair of two
    order moves (50 before 40, 51 before 40) does (50/51 don't interfere)."""
    nodes = {
        40: IGNode(40, {0, 50, 51}, {0: 0}, 3, False, 3),
        41: IGNode(41, {0, 50, 51}, {0: 0}, 3, False, 3),
        50: IGNode(50, {0, 40, 41}, {0: 0}, 3, False, 4),
        51: IGNode(51, {0, 40, 41}, {0: 0}, 3, False, 4),
    }
    return IG(class_id=0, select_order=[40, 41, 50, 51], nodes=nodes,
              decision_igs={40, 41, 50, 51})


_PAIR_TARGET = {50: 3, 51: 3}


def _admit_all(p, ctx):
    return FilterVerdict(admit=True)


# --- generators ---
def test_normalize_kinds_expands_edge():
    # codex major 6: the advertised default "node-add,edge,order" must expand.
    assert normalize_kinds(["node-add", "edge", "order"]) == (
        "node-add", "edge-add", "edge-remove", "order")
    assert normalize_kinds(["edge-add"]) == ("edge-add",)


def test_implicated_1hop_is_target_plus_neighbors():
    assert implicated_nodes(_ig(), phys_target={41: 30}, hops=1) == {41, 40, 42}


def test_implicated_2hop_widens_capped():
    impl = implicated_nodes(_ig(), phys_target={41: 30}, hops=2, cap=64)
    assert {40, 41, 42, 43} <= impl


def test_use_set_family_is_bounded_four():
    assert 1 <= len(use_set_family(_ig(), v=42)) <= 4


def test_insertion_positions_are_two():
    assert set(insertion_positions(_ig(), v=42)) == {"before", "after"}


# --- single enumeration: tallies + window bucket + budget floors ---
def test_enumerate_single_tallies_filter_counts():
    def filt(p, ctx):
        if p.kind is not PerturbationKind.NODE_ADD:
            return FilterVerdict(admit=True)
        if p.target_ig == 41:
            return FilterVerdict(admit=False, reason="rejected_a")
        if p.target_ig == 42:
            return FilterVerdict(admit=False, flag="flagged_c")
        return FilterVerdict(admit=True)

    res = enumerate_single(_ig(), phys_target={42: 27}, config=EnumConfig(),
                           filter_fn=filt, probe_ctx_fn=lambda p: None)
    assert isinstance(res, EnumResult)
    fc = res.filter_counts
    assert fc["candidates_generated"] > 0
    assert fc["rejected_a"] > 0 and fc["flagged_c"] > 0
    assert set(fc) == {"candidates_generated", "rejected_a", "rejected_b",
                       "flagged_c", "rejected_survival"}
    # flagged candidates are EVALUATED into the window bucket, not dropped.
    assert isinstance(res.window_order_hits, list)
    assert set(res.evals_per_kind) == {"node-add", "edge", "order"}


def test_per_kind_floors_reserve_edge_and_order():
    cfg = EnumConfig(eval_cap=200_000, edge_floor=10_000, order_floor=10_000)
    assert cfg.node_add_budget() == 180_000


def test_full_hits_record_assignment_delta():
    res = enumerate_single(_pair_only_ig(), phys_target={50: 3},
                           config=EnumConfig(), filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    # single order move (50 before 40) meets the one-target case -> FULL hit
    assert res.full_hits, "expected a full hit for the single-target case"
    hit = res.full_hits[0]
    assert "delta" in hit and 50 in hit["delta"]


# --- pair composition (codex blocker 1) ---
def test_pair_only_ig_has_no_single_full_hit_exhaustive():
    big = EnumConfig(eval_cap=10_000_000, edge_floor=4_000_000,
                     order_floor=4_000_000)
    res = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                           config=big, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.full_hits == [], "construction is single-solvable — fix fixture"
    assert res.partial_hits, "order-move partials must exist for the frontier"


def test_compose_frontier_pairs_finds_the_working_pair():
    cfg = EnumConfig()
    single = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                              config=cfg, filter_fn=_admit_all,
                              probe_ctx_fn=lambda p: None)
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:cfg.frontier]
    out = compose_frontier_pairs(_pair_only_ig(), _PAIR_TARGET, frontier, cfg,
                                 evals_used=sum(single.evals_per_kind.values()))
    assert out["pair_hits"], "the known working pair was not found"
    kinds = {tuple(sorted((p1.kind.value, p2.kind.value)))
             for p1, p2 in (h["perturbations"] for h in out["pair_hits"])}
    assert ("order", "order") in kinds
    assert out["pair_evals"] > 0 and out["truncated"] is False


def test_compose_frontier_pairs_respects_remaining_budget():
    # Normal single run builds a real (>=2 entry) frontier; then hand compose
    # an EXHAUSTED budget — it must evaluate nothing and flag truncation.
    cfg = EnumConfig()
    single = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                              config=cfg, filter_fn=_admit_all,
                              probe_ctx_fn=lambda p: None)
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:cfg.frontier]
    assert len(frontier) >= 2
    out = compose_frontier_pairs(_pair_only_ig(), _PAIR_TARGET, frontier, cfg,
                                 evals_used=cfg.eval_cap)   # budget exhausted
    assert out["pair_evals"] == 0 and out["truncated"] is True


def test_per_kind_budget_hit_continues_to_next_kind():
    # spec §2.1: the floors are GUARANTEED — exhausting node-add's budget must
    # not abort enumeration before edge/order run.
    cfg = EnumConfig(eval_cap=22, edge_floor=10, order_floor=10)  # node-add: 2
    res = enumerate_single(_pair_only_ig(), phys_target=_PAIR_TARGET,
                           config=cfg, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.truncated is True                      # node-add hit its budget
    assert res.evals_per_kind["node-add"] == 2
    assert res.evals_per_kind["edge"] > 0             # floors still consumed
    assert res.evals_per_kind["order"] > 0
    assert res.last_kind == "order"                   # all kinds visited


# --- escalation gating (finding 3) ---
def test_escalation_fires_on_no_actionable_single_not_zero_hits():
    calls = {"pairs_ran": False}

    def fake_single(*a, **k):
        return EnumResult(
            full_hits=[{"actionable": False, "targets_met": 2, "delta": {}}],
            partial_hits=[], window_order_hits=[],
            filter_counts={"candidates_generated": 1, "rejected_a": 0,
                           "rejected_b": 0, "flagged_c": 0, "rejected_survival": 0},
            evals_per_kind={"node-add": 1, "edge": 0, "order": 0},
            truncated=False, last_kind="node-add")

    def fake_pairs(ig, pt, frontier, cfg, *, evals_used):
        calls["pairs_ran"] = True
        return {"ran": True, "reason": "no actionable single",
                "frontier_size": len(frontier), "frontier": frontier,
                "pair_hits": [], "pair_evals": 0, "truncated": False}

    out = enumerate_with_escalation(
        _ig(), phys_target={42: 27}, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=fake_single, _pair_impl=fake_pairs)
    assert calls["pairs_ran"] is True
    assert out["pair_escalation"]["ran"] is True


def test_escalation_skipped_when_actionable_single_exists():
    def fake_single(*a, **k):
        return EnumResult(
            full_hits=[{"actionable": True, "targets_met": 2, "delta": {}}],
            partial_hits=[], window_order_hits=[],
            filter_counts={"candidates_generated": 1, "rejected_a": 0,
                           "rejected_b": 0, "flagged_c": 0, "rejected_survival": 0},
            evals_per_kind={"node-add": 1, "edge": 0, "order": 0},
            truncated=False, last_kind="node-add")

    out = enumerate_with_escalation(
        _ig(), phys_target={42: 27}, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=fake_single,
        _pair_impl=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")))
    assert out["pair_escalation"]["ran"] is False


def test_default_pair_impl_is_production_compose():
    # Without injection, escalation runs the REAL compose_frontier_pairs and
    # FINDS the pair on the pair-only IG (codex blocker 1: not a stub).
    out = enumerate_with_escalation(
        _pair_only_ig(), phys_target=_PAIR_TARGET, config=EnumConfig(),
        filter_fn=_admit_all, probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False))
    pe = out["pair_escalation"]
    assert pe["ran"] is True and pe["pair_hits"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_enumerate.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `enumerate.py`**

Create `tools/melee-agent/src/search/solver/enumerate.py`:

```python
"""§2.1 bounded generators + single/pair enumeration + 200k cap with reserved
per-kind floors (spec §2 steps 3/5, §2.1).

Bounds: implicated_nodes = 1-hop (spike-checked widen-to-2-hop, cap 64);
use_set_family = fixed 4; insertion_positions = 2. Eval cap 200k; edge + order
each reserve a 10k floor (node-add gets >=180k). The advertised kind vocabulary
is {node-add, edge, order}; `edge` NORMALIZES to edge-add + edge-remove (codex
major 6). Filter verdicts are TALLIED (filter_summary counts) and flagged_c
candidates are still EVALUATED into window_order_hits (spec §1.5 (c)).

compose_frontier_pairs is the PRODUCTION pair body (codex blocker 1): apply both
perturbations, predict, record FULL pair hits, charge the remaining global
budget. Pairs fire when NO actionable single exists (finding 3), not zero hits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.mwcc_debug.tiebreak import IG, predict_assignments
from src.search.solver.perturbations import apply
from src.search.solver.types import Perturbation, PerturbationKind

_ADVERTISED_KINDS = ("node-add", "edge", "order")
_INTERNAL_KINDS = {"node-add", "edge-add", "edge-remove", "order"}


def normalize_kinds(kinds) -> tuple:
    """Expand the advertised vocabulary to internal generator kinds."""
    out: list = []
    for k in kinds:
        k = k.strip()
        if k == "edge":
            out += ["edge-add", "edge-remove"]
        elif k in _INTERNAL_KINDS:
            out.append(k)
        else:
            raise ValueError(f"unknown kind {k!r}; expected "
                             f"{sorted(set(_ADVERTISED_KINDS) | _INTERNAL_KINDS)}")
    return tuple(dict.fromkeys(out))


@dataclass
class EnumConfig:
    eval_cap: int = 200_000
    edge_floor: int = 10_000
    order_floor: int = 10_000
    frontier: int = 32                 # F (tunable; spec §2 step 5 / open Q4)
    implicated_hops: int = 1
    implicated_cap: int = 64
    new_ig_base: int = 100_000         # synthetic ig numbers for V'

    def node_add_budget(self) -> int:
        return self.eval_cap - self.edge_floor - self.order_floor


@dataclass
class EnumResult:
    full_hits: list                    # [{perturbation, targets_met, delta, actionable}]
    partial_hits: list
    window_order_hits: list            # flagged_c, EVALUATED (informational)
    filter_counts: dict                # spec §7 filter_summary keys
    evals_per_kind: dict               # {node-add, edge, order} (spec §7)
    truncated: bool
    last_kind: Optional[str]


def implicated_nodes(ig: IG, phys_target: dict, *, hops: int = 1,
                     cap: int = 64) -> set:
    impl = set(int(k) for k in phys_target)
    frontier = set(impl)
    for _ in range(hops):
        nxt = set()
        for ig_idx in frontier:
            node = ig.nodes.get(ig_idx)
            if node:
                nxt |= {n for n in node.neighbors if n in ig.nodes}
        impl |= nxt
        frontier = nxt
        if len(impl) >= cap:
            break
    return set(sorted(impl)[:cap]) if len(impl) > cap else impl


def use_set_family(ig: IG, v: int) -> list:
    """Fixed small family (spec §2.1), approximated from the IG as subsets of
    v's neighbors. Bounded at 4. Includes the all-uses family (it exists in
    source space; the L1 strict-subset rule rejects it as coalesce-bait — that
    reject must be OBSERVABLE in filter_counts, so it is generated)."""
    node = ig.nodes.get(v)
    if node is None:
        return []
    nbrs = sorted(n for n in node.neighbors if n in ig.nodes)
    families = []
    if nbrs:
        families.append(tuple(nbrs))                 # all uses (L1-reject bait)
        families.append((nbrs[0],))                  # single (hottest proxy)
    if len(nbrs) > 1:
        families.append(tuple(nbrs[1:]))             # uses past first
        families.append(tuple(nbrs[:-1]))            # uses before last
    seen, out = set(), []
    for f in families:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) == 4:
            break
    return out


def insertion_positions(ig: IG, v: int) -> list:
    return ["before", "after"]


def _targets_met(assigns: dict, phys_target: dict) -> int:
    return sum(1 for k, want in phys_target.items() if assigns.get(k) == want)


def _delta(base: dict, assigns: dict, phys_target: dict) -> dict:
    return {k: [base.get(k), assigns.get(k)]
            for k in phys_target if base.get(k) != assigns.get(k)}


def enumerate_single(ig: IG, phys_target: dict, *, config: EnumConfig,
                     filter_fn: Callable, probe_ctx_fn: Callable,
                     kinds=_ADVERTISED_KINDS) -> EnumResult:
    """Enumerate single perturbations kind-by-kind in priority order, applying
    the §1.5 filter (node-add only), tallying verdicts, evaluating flagged_c
    candidates into the window bucket. Honors per-kind floors + the global cap."""
    full, partial, window = [], [], []
    counts = {"candidates_generated": 0, "rejected_a": 0, "rejected_b": 0,
              "flagged_c": 0, "rejected_survival": 0}
    evals = {"node-add": 0, "edge": 0, "order": 0}
    budgets = {"node-add": config.node_add_budget(),
               "edge": config.edge_floor, "order": config.order_floor}
    total_target = len(phys_target)
    truncated, last_kind = False, None
    impl = implicated_nodes(ig, phys_target, hops=config.implicated_hops,
                            cap=config.implicated_cap)
    base = predict_assignments(ig)
    next_new = config.new_ig_base

    def _bucket(kind_str):
        return ("node-add" if kind_str == "node-add"
                else "order" if kind_str == "order" else "edge")

    for kind_str in normalize_kinds(kinds):
        last_kind = kind_str
        bucket = _bucket(kind_str)
        kind_truncated = False
        for v in sorted(impl):
            perts: list = []
            if kind_str == "node-add":
                for use_set in use_set_family(ig, v):
                    for pos in insertion_positions(ig, v):
                        perts.append(Perturbation(
                            PerturbationKind.NODE_ADD, target_ig=v,
                            use_set=use_set, new_ig=next_new, position=pos,
                            interfere_original=True))
                        next_new += 1
            elif kind_str in ("edge-add", "edge-remove"):
                k = (PerturbationKind.EDGE_ADD if kind_str == "edge-add"
                     else PerturbationKind.EDGE_REMOVE)
                perts = [Perturbation(k, target_ig=v, edge=(v, o))
                         for o in sorted(impl - {v})]
            else:  # order
                perts = [Perturbation(PerturbationKind.ORDER, target_ig=v,
                                      order_move=("before", o))
                         for o in sorted(impl - {v})]
            for p in perts:
                counts["candidates_generated"] += 1
                verdict = None
                if p.kind is PerturbationKind.NODE_ADD:
                    verdict = filter_fn(p, probe_ctx_fn(p))
                if verdict is not None and not verdict.admit:
                    if verdict.reason:
                        counts[verdict.reason] += 1
                        continue                      # hard reject: never evaluated
                    if verdict.flag == "flagged_c":
                        counts["flagged_c"] += 1      # quarantine: STILL evaluated
                if evals[bucket] >= budgets[bucket]:
                    # Per-kind budget hit: record truncation and MOVE ON to the
                    # next kind — the reserved floors guarantee edge/order still
                    # run after node-add exhausts its budget (spec §2.1: "the
                    # two 10k floors are then guaranteed regardless of node-add
                    # consumption"). Never abort the whole enumeration here.
                    truncated = True
                    kind_truncated = True
                    break
                try:
                    ig2 = apply(ig, p)
                except Exception:
                    continue
                evals[bucket] += 1
                assigns = predict_assignments(ig2)
                met = _targets_met(assigns, phys_target)
                rec = {"perturbation": p, "targets_met": met,
                       "delta": _delta(base, assigns, phys_target),
                       "actionable": False}
                if verdict is not None and verdict.flag == "flagged_c":
                    window.append(rec)
                elif met >= total_target and total_target > 0:
                    full.append(rec)
                elif met > 0:
                    partial.append(rec)
            if kind_truncated:
                break
        # continue to the next kind regardless (floors guaranteed).
    return EnumResult(full, partial, window, counts, evals, truncated, last_kind)


def compose_frontier_pairs(ig: IG, phys_target: dict, frontier: list,
                           config: EnumConfig, *, evals_used: int) -> dict:
    """PRODUCTION pair composition (codex blocker 1): for each unordered pair of
    frontier entries, apply both perturbations, predict, record FULL pair hits.
    Pair evals charge the REMAINING global budget (eval_cap - evals_used)."""
    budget = max(config.eval_cap - evals_used, 0)
    pair_hits: list = []
    pair_evals = 0
    truncated = budget == 0 and len(frontier) > 1
    total = len(phys_target)
    base = predict_assignments(ig)
    for i in range(len(frontier)):
        if truncated:
            break
        for j in range(i + 1, len(frontier)):
            if pair_evals >= budget:
                truncated = True
                break
            p1 = frontier[i]["perturbation"]
            p2 = frontier[j]["perturbation"]
            if (p1.kind is PerturbationKind.NODE_ADD
                    and p2.kind is PerturbationKind.NODE_ADD
                    and p1.new_ig == p2.new_ig):
                continue                                # synthetic-id collision
            try:
                ig2 = apply(apply(ig, p1), p2)
            except Exception:
                continue
            pair_evals += 1
            assigns = predict_assignments(ig2)
            met = _targets_met(assigns, phys_target)
            if met >= total and total > 0:
                pair_hits.append({
                    "perturbations": (p1, p2), "targets_met": met,
                    "delta": _delta(base, assigns, phys_target),
                    "actionable": False})
    return {"ran": True, "reason": "no actionable single",
            "frontier_size": len(frontier), "frontier": frontier,
            "pair_hits": pair_hits, "pair_evals": pair_evals,
            "truncated": truncated}


def enumerate_with_escalation(ig: IG, phys_target: dict, *, config: EnumConfig,
                              filter_fn: Callable, probe_ctx_fn: Callable,
                              actionable_fn: Callable,
                              _single_impl=enumerate_single,
                              _pair_impl=compose_frontier_pairs) -> dict:
    """Run single enumeration; escalate to PRODUCTION pair composition iff NO
    actionable single exists (finding 3 — a low-confidence/tooling-lead single
    must not suppress pairs)."""
    single = _single_impl(ig, phys_target, config=config, filter_fn=filter_fn,
                          probe_ctx_fn=probe_ctx_fn)
    if any(actionable_fn(h) for h in single.full_hits):
        return {"single": single,
                "pair_escalation": {"ran": False,
                                    "reason": "actionable single exists",
                                    "frontier_size": 0, "frontier": [],
                                    "pair_hits": [], "pair_evals": 0,
                                    "truncated": False}}
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:config.frontier]
    pair = _pair_impl(ig, phys_target, frontier, config,
                      evals_used=sum(single.evals_per_kind.values()))
    return {"single": single, "pair_escalation": pair}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_enumerate.py -q --no-cov`
Expected: PASS (15 tests). The pair-only construction is verified by `test_pair_only_ig_has_no_single_full_hit_exhaustive` (the brute-force no-single confirmation) — if it fails, the construction is single-solvable and must be adjusted before proceeding.

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/enumerate.py tools/melee-agent/tests/search/solver/test_enumerate.py && git commit -m "feat(solver): enumerate.py — bounded generators, kind normalization, filter tallies, PRODUCTION pair composition (T5)"
```

---

### Task 6: `worksheet.py` — the §7 schema dataclass + serialize

The §7 schema VERBATIM, plus the one recorded extension: `pair_escalation.pair_hits` (so N7's "finds the pair" and §4.1's "no actionable pair" are reportable — see Deviations). Pins `classify_confidence` (spec §7/finding rev2-6).

**Files:**
- Create: `tools/melee-agent/src/search/solver/worksheet.py`
- Create: `tools/melee-agent/tests/search/solver/test_worksheet.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_worksheet.py`:

```python
import json

from src.search.solver.worksheet import (
    Candidate, FilterSummary, PairEscalation, Worksheet, classify_confidence,
)


def test_classify_confidence_high_requires_full_vector_and_tier_a():
    assert classify_confidence(full_vector=True, has_tier_a_source_object=True) == "high"
    assert classify_confidence(full_vector=False, has_tier_a_source_object=True) == "proposal"
    assert classify_confidence(full_vector=True, has_tier_a_source_object=False) == "proposal"


def test_worksheet_serializes_exact_schema_keys():
    cand = Candidate(
        rank=1,
        perturbation={"kind": "node-add", "target_ig": 41, "use_set": [42]},
        predicted_assignment_delta={"42": [29, 27]},
        c_realizations=[{"lever": "alias", "source_object": "data_alias",
                         "confidence_tier": "a"}],
        surrogate_confidence="high",
        fidelity_gate="pending",
    )
    ws = Worksheet(
        function="mnDiagram_80241E78", class_id=0, g1_rate=1.0,
        force_phys_target={"42": 27}, reachable=True,
        filter_summary=FilterSummary(candidates_generated=12, rejected_a=1,
                                     rejected_b=1, flagged_c=0, rejected_survival=2),
        candidates=[cand], tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(ran=False, reason="actionable single exists",
                                       frontier_size=0, frontier=[], pair_hits=[]),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 8, "edge": 2, "order": 2},
    )
    payload = json.loads(ws.to_json())
    assert set(payload) == {
        "function", "class_id", "g1_rate", "force_phys_target", "reachable",
        "filter_summary", "candidates", "tooling_leads", "window_order",
        "pair_escalation", "enumeration_truncated", "evals_per_kind",
    }
    assert set(payload["filter_summary"]) == {
        "candidates_generated", "rejected_a", "rejected_b", "flagged_c",
        "rejected_survival",
    }
    c = payload["candidates"][0]
    assert set(c) == {
        "rank", "perturbation", "predicted_assignment_delta", "c_realizations",
        "surrogate_confidence", "fidelity_gate",
    }
    assert c["surrogate_confidence"] in {"high", "proposal"}
    assert c["fidelity_gate"] == "pending"
    assert set(c["c_realizations"][0]) == {"lever", "source_object", "confidence_tier"}
    # pair_escalation: spec keys + the recorded pair_hits extension (Deviations).
    assert set(payload["pair_escalation"]) == {
        "ran", "reason", "frontier_size", "frontier", "pair_hits",
    }
    assert set(payload["evals_per_kind"]) == {"node-add", "edge", "order"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_worksheet.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `worksheet.py`**

Create `tools/melee-agent/src/search/solver/worksheet.py`:

```python
"""§7 worksheet schema (verbatim field names) + serialization.

surrogate_confidence (spec §7 / finding rev2-6):
  "high"     iff the surrogate reproduces the FULL target vector for EVERY
             contested register AND the perturbation has a resolved source
             object with a tier-a C realization;
  "proposal" otherwise.
Driver contract: high = apply-now, proposal = investigate-first. §3 runs on both.

Schema extension (recorded in the plan's Deviations): pair_escalation carries a
`pair_hits` list so the §4.1 "no actionable pair" verdict and N7's "finds the
pair" criterion are reportable. All other keys are spec-verbatim.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


def classify_confidence(*, full_vector: bool, has_tier_a_source_object: bool) -> str:
    return "high" if (full_vector and has_tier_a_source_object) else "proposal"


@dataclass
class FilterSummary:
    candidates_generated: int
    rejected_a: int
    rejected_b: int
    flagged_c: int
    rejected_survival: int


@dataclass
class Candidate:
    rank: int
    perturbation: dict                  # {kind, target_ig, use_set?, edge?, order_move?}
    predicted_assignment_delta: dict
    c_realizations: list                # [{lever, source_object, confidence_tier}]
    surrogate_confidence: str           # "high" | "proposal"
    fidelity_gate: str = "pending"


@dataclass
class PairEscalation:
    ran: bool
    reason: str
    frontier_size: int
    frontier: list = field(default_factory=list)
    pair_hits: list = field(default_factory=list)   # recorded schema extension


@dataclass
class Worksheet:
    function: str
    class_id: int
    g1_rate: float
    force_phys_target: dict
    reachable: bool
    filter_summary: FilterSummary
    candidates: list                    # [Candidate | dict]
    tooling_leads: list
    window_order: list
    pair_escalation: PairEscalation
    enumeration_truncated: bool
    evals_per_kind: dict                # {node-add, edge, order}

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "class_id": self.class_id,
            "g1_rate": self.g1_rate,
            "force_phys_target": self.force_phys_target,
            "reachable": self.reachable,
            "filter_summary": asdict(self.filter_summary),
            "candidates": [c if isinstance(c, dict) else asdict(c)
                           for c in self.candidates],
            "tooling_leads": list(self.tooling_leads),
            "window_order": list(self.window_order),
            "pair_escalation": asdict(self.pair_escalation),
            "enumeration_truncated": self.enumeration_truncated,
            "evals_per_kind": dict(self.evals_per_kind),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_worksheet.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/worksheet.py tools/melee-agent/tests/search/solver/test_worksheet.py && git commit -m "feat(solver): worksheet.py — §7 schema (verbatim) + pair_hits extension + classify_confidence (T6)"
```

---

### Task 7: `realize.py` — catalog, source objects, tiering, and the TESTED `assemble_realized` (codex major 10)

Catalog C-realization + source-object lookup + lever-priority ranking, AND the full assembly layer `assemble_realized` that turns an `enumerate_with_escalation` output into worksheet inputs: no-source-object hits → `tooling_leads`, window-flagged evaluated hits → `window_order` rows, exact `FilterSummary` pass-through, `classify_confidence` per candidate, rank assignment (lever tier, then perturbation size, then assignment churn — spec §2 step 4 tie-break), and pair-hit enrichment (a pair is actionable iff BOTH perturbations resolve source objects with realizations). This is production code consumed by the Task-11 calibration gate and the Task-14 CLI — not a CLI-local hand-wave.

**Files:**
- Create: `tools/melee-agent/src/search/solver/realize.py`
- Create: `tools/melee-agent/tests/search/solver/test_realize.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_realize.py`:

```python
from src.search.solver.enumerate import EnumResult
from src.search.solver.realize import (
    CRealization, assemble_realized, lever_priority_rank, load_catalog,
    realize_perturbation,
)
from src.search.solver.types import Perturbation, PerturbationKind


_CATALOG = {
    "node-add": [
        {"lever": "alias", "tier": "a", "note": "T* a = x;"},
        {"lever": "temp-for-expr", "tier": "a", "note": "T t = expr;"},
    ],
    "edge-add": [{"lever": "statement-hoist-sink", "tier": "b", "note": "..."}],
    "edge-remove": [{"lever": "statement-hoist-sink", "tier": "b", "note": "..."}],
    "order": [{"lever": "decl-reorder", "tier": "c", "note": "census caveat"}],
}


def _node_add(target=41, new_ig=99):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=target,
                        use_set=(42,), new_ig=new_ig, position="after",
                        interfere_original=True)


def test_load_catalog_from_inline_dict_and_dir(tmp_path):
    assert load_catalog(_CATALOG)["node-add"][0]["lever"] == "alias"
    import json
    (tmp_path / "node-add.json").write_text(json.dumps(_CATALOG["node-add"]))
    cat = load_catalog(tmp_path)
    assert cat["node-add"][0]["lever"] == "alias"


def test_realize_orders_by_priority_and_carries_source_object():
    reals = realize_perturbation(_node_add(), _CATALOG, source_object="data_alias")
    assert reals and reals[0].lever == "alias" and reals[0].confidence_tier == "a"
    assert reals[0].source_object == "data_alias"


def test_no_source_object_yields_empty_realizations():
    assert realize_perturbation(_node_add(), _CATALOG, source_object=None) == []


def test_lever_priority_node_set_over_edge_over_order():
    a = CRealization("alias", "a", "obj")
    b = CRealization("statement-hoist-sink", "b", "obj")
    c = CRealization("decl-reorder", "c", "obj")
    assert [r.confidence_tier for r in sorted([c, b, a], key=lever_priority_rank)] \
        == ["a", "b", "c"]


# ---- assemble_realized (codex major 10) ----

def _enum_out(full_hits, window_hits=(), pair_hits=(), pair_ran=False):
    single = EnumResult(
        full_hits=list(full_hits), partial_hits=[],
        window_order_hits=list(window_hits),
        filter_counts={"candidates_generated": 10, "rejected_a": 2,
                       "rejected_b": 1, "flagged_c": len(window_hits),
                       "rejected_survival": 1},
        evals_per_kind={"node-add": 6, "edge": 2, "order": 2},
        truncated=False, last_kind="order")
    pe = {"ran": pair_ran, "reason": "no actionable single" if pair_ran
          else "actionable single exists", "frontier_size": 0, "frontier": [],
          "pair_hits": list(pair_hits), "pair_evals": len(pair_hits),
          "truncated": False}
    return {"single": single, "pair_escalation": pe}


def test_assemble_routes_no_source_hits_to_tooling_leads():
    hit = {"perturbation": _node_add(target=50), "targets_met": 1,
           "delta": {"50": [22, 21]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={50: 21}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: None)
    assert bundle.candidates == []
    assert len(bundle.tooling_leads) == 1
    assert bundle.tooling_leads[0]["perturbation"]["target_ig"] == 50


def test_assemble_builds_high_confidence_candidate():
    hit = {"perturbation": _node_add(target=41), "targets_met": 1,
           "delta": {"41": [30, 27]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "data_alias")
    assert len(bundle.candidates) == 1
    c = bundle.candidates[0]
    assert c["rank"] == 1
    assert c["surrogate_confidence"] == "high"      # full vector + tier-a + source
    assert c["fidelity_gate"] == "pending"
    assert c["perturbation"] == {"kind": "node-add", "target_ig": 41,
                                 "use_set": [42]}
    assert c["c_realizations"][0]["confidence_tier"] == "a"
    # mutually exclusive routing: an actionable candidate is not a lead.
    assert bundle.tooling_leads == []


def test_assemble_edge_hit_is_proposal_tier():
    p = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    hit = {"perturbation": p, "targets_met": 1, "delta": {"88": [26, 25]},
           "actionable": False}
    bundle = assemble_realized(
        _enum_out([hit]), phys_target={88: 25}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "row_text")
    assert bundle.candidates[0]["surrogate_confidence"] == "proposal"   # tier b


def test_assemble_routes_window_hits_to_window_order():
    whit = {"perturbation": _node_add(target=60), "targets_met": 1,
            "delta": {"60": [22, 21]}, "actionable": False}
    bundle = assemble_realized(
        _enum_out([], window_hits=[whit]), phys_target={60: 21},
        catalog=_CATALOG, source_lookup=lambda ig_idx: "table_copy")
    assert bundle.candidates == []
    assert len(bundle.window_order) == 1
    assert bundle.window_order[0]["residual"] == "allocation-window"


def test_assemble_filter_summary_passthrough_and_evals():
    bundle = assemble_realized(
        _enum_out([]), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: None)
    assert bundle.filter_summary == {"candidates_generated": 10, "rejected_a": 2,
                                     "rejected_b": 1, "flagged_c": 0,
                                     "rejected_survival": 1}
    assert bundle.evals_per_kind == {"node-add": 6, "edge": 2, "order": 2}


def test_assemble_enriches_pair_hits_actionability():
    p1 = _node_add(target=41, new_ig=100)
    p2 = _node_add(target=43, new_ig=101)
    ph = {"perturbations": (p1, p2), "targets_met": 2, "delta": {},
          "actionable": False}
    bundle = assemble_realized(
        _enum_out([], pair_hits=[ph], pair_ran=True), phys_target={41: 27, 43: 26},
        catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj" if ig_idx in (41, 43) else None)
    enriched = bundle.pair_escalation["pair_hits"][0]
    assert enriched["actionable"] is True
    assert [pp["target_ig"] for pp in enriched["perturbations"]] == [41, 43]

    bundle2 = assemble_realized(
        _enum_out([], pair_hits=[ph], pair_ran=True), phys_target={41: 27, 43: 26},
        catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj" if ig_idx == 41 else None)
    assert bundle2.pair_escalation["pair_hits"][0]["actionable"] is False


def test_assemble_ranking_tier_then_churn():
    p_alias = _node_add(target=41, new_ig=100)
    p_edge = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    hits = [
        {"perturbation": p_edge, "targets_met": 1, "delta": {"88": [26, 25]},
         "actionable": False},
        {"perturbation": p_alias, "targets_met": 1, "delta": {"41": [30, 27]},
         "actionable": False},
    ]
    bundle = assemble_realized(
        _enum_out(hits), phys_target={41: 27}, catalog=_CATALOG,
        source_lookup=lambda ig_idx: "obj")
    # tier-a node-add ranks above tier-b edge regardless of input order.
    assert bundle.candidates[0]["perturbation"]["kind"] == "node-add"
    assert bundle.candidates[0]["rank"] == 1
    assert bundle.candidates[1]["rank"] == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_realize.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `realize.py`**

Create `tools/melee-agent/src/search/solver/realize.py`:

```python
"""Perturbation -> lever-catalog C-realization + assembly into worksheet inputs
(spec §2 step 4, §7; codex major 10 — assemble_realized is production, tested).

Lever priority (spec §2 step 4): node-set (a) > edge (b) > order (c); within
node-set: alias > temp-for-expr > anchoring > per-loop-local > inline-base-cast.
Tie-break: perturbation SIZE then assignment churn (delta count).

A perturbation with NO resolved source object is non-actionable telemetry ->
tooling_leads, never a worksheet candidate (finding 7). Window-flagged evaluated
hits -> window_order rows (informational, never exit-0/apply).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.search.solver.types import Perturbation, serialize_perturbation
from src.search.solver.worksheet import classify_confidence

_NODE_SET_ORDER = ["alias", "temp-for-expr", "anchoring", "per-loop-local",
                   "inline-base-cast"]
_TIER_RANK = {"a": 0, "b": 1, "c": 2}


@dataclass(frozen=True)
class CRealization:
    lever: str
    confidence_tier: str          # "a" | "b" | "c" (spec §7 confidence_tier)
    source_object: Optional[str]
    note: str = ""


@dataclass
class RealizedBundle:
    """assemble_realized output — the worksheet inputs."""
    candidates: list              # actionable, ranked, schema-shaped dicts
    tooling_leads: list
    window_order: list
    filter_summary: dict          # spec §7 filter_summary keys
    evals_per_kind: dict          # {node-add, edge, order}
    pair_escalation: dict         # enriched pair block (incl. pair_hits)
    enumeration_truncated: bool = False
    last_kind: Optional[str] = None


def load_catalog(source) -> dict:
    """kind->levers catalog from an inline dict (unit fixtures) or a directory
    of per-kind JSON files (<kind>.json: [{lever, tier, note}])."""
    if isinstance(source, dict):
        return dict(source)
    cat: dict = {}
    d = Path(source)
    for kind in ("node-add", "edge-add", "edge-remove", "order"):
        f = d / f"{kind}.json"
        if f.exists():
            cat[kind] = json.loads(f.read_text())
    return cat


def realize_perturbation(p: Perturbation, catalog, *,
                         source_object: Optional[str]) -> list:
    """Map a perturbation to C realizations; [] when no source object."""
    if source_object is None:
        return []
    entries = catalog.get(p.kind.value, [])
    reals = [CRealization(e["lever"], e["tier"], source_object, e.get("note", ""))
             for e in entries]
    reals.sort(key=lever_priority_rank)
    return reals


def lever_priority_rank(r: CRealization) -> tuple:
    tier = _TIER_RANK.get(r.confidence_tier, 9)
    within = (_NODE_SET_ORDER.index(r.lever)
              if r.lever in _NODE_SET_ORDER else 99)
    return (tier, within)


def _reals_dicts(reals: list) -> list:
    return [{"lever": r.lever, "source_object": r.source_object,
             "confidence_tier": r.confidence_tier} for r in reals]


def assemble_realized(enum_out: dict, *, phys_target: dict, catalog,
                      source_lookup: Callable[[int], Optional[str]],
                      ) -> RealizedBundle:
    """Turn enumerate_with_escalation output into worksheet inputs.

    Routing: FULL hits with a resolved source object -> ranked candidates;
    FULL hits without -> tooling_leads; window_order_hits -> window_order rows;
    pair_hits enriched with actionability (BOTH ends resolve + realize).
    """
    single = enum_out["single"]
    total = len(phys_target)

    scored: list = []      # (sort_key, candidate_dict)
    leads: list = []
    for hit in single.full_hits:
        p: Perturbation = hit["perturbation"]
        src_obj = source_lookup(p.target_ig)
        reals = realize_perturbation(p, catalog, source_object=src_obj)
        if not reals:
            leads.append({"perturbation": serialize_perturbation(p),
                          "targets_met": hit["targets_met"],
                          "predicted_assignment_delta": hit.get("delta", {}),
                          "note": "no resolved source object (non-actionable)"})
            continue
        best = reals[0]
        conf = classify_confidence(
            full_vector=(total > 0 and hit["targets_met"] >= total),
            has_tier_a_source_object=(best.confidence_tier == "a"
                                      and best.source_object is not None))
        churn = len(hit.get("delta", {}))
        scored.append((
            (lever_priority_rank(best), 1, churn),   # tier, size=1, churn
            {"perturbation": serialize_perturbation(p),
             "predicted_assignment_delta": hit.get("delta", {}),
             "c_realizations": _reals_dicts(reals),
             "surrogate_confidence": conf,
             "fidelity_gate": "pending"},
        ))
    scored.sort(key=lambda t: t[0])
    candidates = []
    for rank, (_key, cand) in enumerate(scored, start=1):
        candidates.append({"rank": rank, **cand})

    window_rows = []
    for hit in single.window_order_hits:
        p = hit["perturbation"]
        window_rows.append({
            "perturbation": serialize_perturbation(p),
            "predicted_assignment_delta": hit.get("delta", {}),
            "residual": "allocation-window",
            "source_object": source_lookup(p.target_ig),
        })

    pe = dict(enum_out["pair_escalation"])
    enriched_pairs = []
    for ph in pe.get("pair_hits", []):
        p1, p2 = ph["perturbations"]
        ok = all(
            realize_perturbation(pp, catalog,
                                 source_object=source_lookup(pp.target_ig))
            for pp in (p1, p2)
        )
        enriched_pairs.append({
            "perturbations": [serialize_perturbation(p1),
                              serialize_perturbation(p2)],
            "targets_met": ph["targets_met"],
            "predicted_assignment_delta": ph.get("delta", {}),
            "actionable": bool(ok),
        })
    pe["pair_hits"] = enriched_pairs    # pair_evals/truncated kept as telemetry

    return RealizedBundle(
        candidates=candidates, tooling_leads=leads, window_order=window_rows,
        filter_summary=dict(single.filter_counts),
        evals_per_kind=dict(single.evals_per_kind),
        pair_escalation=pe,
        enumeration_truncated=single.truncated,
        last_kind=single.last_kind,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_realize.py -q --no-cov`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/realize.py tools/melee-agent/tests/search/solver/test_realize.py && git commit -m "feat(solver): realize.py — catalog + tiering + TESTED assemble_realized (leads/window/pairs/ranking) (T7)"
```

---

### Task 8: `gate.py` — §3 fidelity gate with STRUCTURAL no-op detection (codex major 9)

Spec §3 defines a no-op as "a perturbation that doesn't change the IG" — so the live seam detects it STRUCTURALLY (select order + node set + per-node neighbor sets identical to the baseline IG), never from prediction equality (which would mark a real, perfectly-predicted landing UNATTRIBUTED). Classification outcomes: `surrogate-confirmed`, `fidelity-miss` (MODEL GAP), `realization-miss`, `g1-broken`, `UNATTRIBUTED`.

**Files:**
- Create: `tools/melee-agent/src/search/solver/gate.py`
- Create: `tools/melee-agent/tests/search/solver/test_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_gate.py`:

```python
from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.gate import (
    GateOutcome, classify_fidelity, ig_structurally_equal,
)


def _ig(extra_node=False):
    nodes = {
        41: IGNode(41, {42}, {}, 1, False, 30),
        42: IGNode(42, {41}, {}, 1, False, 29),
    }
    order = [41, 42]
    if extra_node:
        nodes[99] = IGNode(99, {41}, {}, 1, False, 27)
        nodes[41].neighbors = {42, 99}
        order = [41, 99, 42]
    return IG(class_id=0, select_order=order, nodes=nodes,
              decision_igs=set(nodes))


def test_structural_equality_detects_identity_and_difference():
    assert ig_structurally_equal(_ig(), _ig()) is True
    assert ig_structurally_equal(_ig(), _ig(extra_node=True)) is False


def test_confirmed_when_present_and_assignments_match():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={41: 30, 99: 27}, actual={41: 30, 99: 27},
        phys_target={99: 27}, no_op=False)
    assert out.classification == "surrogate-confirmed" and out.is_win is True


def test_perfectly_predicted_real_landing_is_not_noop():
    # codex major 9: prediction equality must NOT imply no-op. A real landing
    # whose prediction matches exactly is CONFIRMED (no_op comes from the
    # STRUCTURAL IG comparison, which is False here).
    base, patched = _ig(), _ig(extra_node=True)
    assert ig_structurally_equal(patched, base) is False
    out = classify_fidelity(
        new_ig=99, perturbation_present=(99 in patched.nodes), g1_rate=1.0,
        predicted={99: 27}, actual={99: 27}, phys_target={99: 27},
        no_op=ig_structurally_equal(patched, base))
    assert out.classification == "surrogate-confirmed"


def test_fidelity_miss_present_but_differs_is_model_gap():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={99: 27}, actual={99: 26},
        phys_target={99: 27}, no_op=False)
    assert out.classification == "fidelity-miss"
    assert out.is_win is False and out.model_gap is True


def test_realization_miss_when_perturbation_absent():
    out = classify_fidelity(
        new_ig=99, perturbation_present=False, g1_rate=1.0,
        predicted={99: 27}, actual={}, phys_target={99: 27}, no_op=False)
    assert out.classification == "realization-miss" and out.is_win is False


def test_no_op_is_unattributed_never_a_win():
    out = classify_fidelity(
        new_ig=99, perturbation_present=False, g1_rate=1.0,
        predicted={}, actual={}, phys_target={99: 27}, no_op=True)
    assert out.classification == "UNATTRIBUTED" and out.is_win is False


def test_g1_broken_voids_prediction():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=0.8,
        predicted={99: 27}, actual={99: 27}, phys_target={99: 27}, no_op=False)
    assert out.classification == "g1-broken" and out.is_win is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_gate.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `gate.py`**

Create `tools/melee-agent/src/search/solver/gate.py`:

```python
"""§3 fidelity gate — the AFTER-application attribution (the §1.5 remainder).

Outcomes (spec §3):
  surrogate-confirmed : perturbation present + assignments meet the target.
  fidelity-miss       : present + DIFFER -> MODEL GAP datum (NOT "MWCC quirk").
  realization-miss    : perturbation absent -> the C mapping was wrong.
  g1-broken           : G1 < 100% on the patched IG -> prediction void, STOP.
  UNATTRIBUTED        : a no-op perturbation -> never a win (reuses the
                        DirectedMeta.non_actionable discipline).

No-op is detected STRUCTURALLY (spec §3: "one that doesn't change the IG"):
ig_structurally_equal compares select order, node set, and per-node neighbor
sets against the BASELINE IG. Prediction equality is NEVER the no-op signal
(codex major 9 — a real, perfectly-predicted landing must confirm, not void).

classify_fidelity is PURE; re_extract_and_classify is the live seam (fresh
`debug dump local` of the patched source) exercised at the pilots.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.mwcc_debug.tiebreak import IG


@dataclass
class GateOutcome:
    classification: str   # surrogate-confirmed | fidelity-miss | realization-miss | g1-broken | UNATTRIBUTED
    is_win: bool
    model_gap: bool = False
    detail: str = ""


def ig_structurally_equal(a: IG, b: IG) -> bool:
    """Structural IG identity: same select order, node set, and neighbor sets."""
    if a is None or b is None:
        return False
    if a.select_order != b.select_order:
        return False
    if set(a.nodes) != set(b.nodes):
        return False
    return all(set(a.nodes[k].neighbors) == set(b.nodes[k].neighbors)
               for k in a.nodes)


def classify_fidelity(*, new_ig, perturbation_present, g1_rate, predicted,
                      actual, phys_target, no_op) -> GateOutcome:
    if no_op:
        return GateOutcome("UNATTRIBUTED", False,
                           detail="no-op perturbation: patched IG structurally "
                                  "identical to baseline")
    if g1_rate < 1.0:
        return GateOutcome("g1-broken", False,
                           detail=f"G1 {g1_rate:.3f} on patched IG; prediction void")
    if not perturbation_present:
        return GateOutcome("realization-miss", False,
                           detail="perturbation absent from re-extracted IG")
    meets = all(actual.get(k) == want for k, want in phys_target.items())
    if meets:
        return GateOutcome("surrogate-confirmed", True)
    diverged = {k: (predicted.get(k), actual.get(k))
                for k in phys_target if predicted.get(k) != actual.get(k)}
    return GateOutcome("fidelity-miss", False, model_gap=True,
                       detail=f"present but assignments differ: {diverged}")


def re_extract_and_classify(*, patched_pcdump_text, function, class_id, new_ig,
                            phys_target, predicted_assignments, baseline_ig):
    """Live seam: load the patched IG, detect structural no-op vs baseline_ig,
    re-run G1, detect the new node, compare predicted vs actual."""
    from src.mwcc_debug import tiebreak as tb
    ig = tb.load_ig(patched_pcdump_text, function, class_id=class_id)
    if ig is None:
        return GateOutcome("realization-miss", False,
                           detail="no COLORGRAPH section in patched dump")
    g1 = tb.validate_g1(ig, function)
    return classify_fidelity(
        new_ig=new_ig,
        perturbation_present=new_ig in ig.nodes,
        g1_rate=g1.rate,
        predicted=predicted_assignments,
        actual=tb.predict_assignments(ig),
        phys_target=phys_target,
        no_op=ig_structurally_equal(ig, baseline_ig))
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_gate.py -q --no-cov`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/gate.py tools/melee-agent/tests/search/solver/test_gate.py && git commit -m "feat(solver): gate.py — §3 fidelity gate with STRUCTURAL no-op detection (T8)"
```

---

### Task 9: `solve.py` — orchestration + exit-code contract (incl. the empty-target abstain guard)

The §2 loop with the spec §7 exit contract, INCLUDING (codex major 7 — in THIS task, before its commit, not deferred to the negative controls):
- `0` = ≥1 ACTIONABLE perturbation (resolved source object) found — singles OR actionable pairs;
- `3` = abstain (G1 imperfect / force-phys collision / target truncated / **empty force-phys target — matched, nothing to reach**);
- `4` = budgeted no-candidate within K/F/cap/filter; `reason: window-order` when ALL surviving hits are window-order-flagged.

**Files:**
- Create: `tools/melee-agent/src/search/solver/solve.py`
- Create: `tools/melee-agent/tests/search/solver/test_solve.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_solve.py`:

```python
from src.search.solver.realize import RealizedBundle
from src.search.solver.solve import Preconditions, SolveResult, solve_coloring


def _ok_pre(**over):
    base = dict(register_only=True, reachable=True, g1_rate=1.0,
                phys_target={42: 27}, g1_truncated=False,
                force_phys_collision=False)
    base.update(over)
    return Preconditions(**base)


def _bundle(candidates=(), leads=(), window=(), pair_hits=(), pair_ran=False):
    return RealizedBundle(
        candidates=list(candidates), tooling_leads=list(leads),
        window_order=list(window),
        filter_summary={"candidates_generated": 4, "rejected_a": 0,
                        "rejected_b": 0, "flagged_c": len(window),
                        "rejected_survival": 0},
        evals_per_kind={"node-add": 4, "edge": 0, "order": 0},
        pair_escalation={"ran": pair_ran,
                         "reason": "no actionable single" if pair_ran
                         else "actionable single exists",
                         "frontier_size": 0, "frontier": [],
                         "pair_hits": list(pair_hits), "pair_evals": 0,
                         "truncated": False},
        enumeration_truncated=False, last_kind="order")


def _cand(rank=1):
    return {"rank": rank, "perturbation": {"kind": "node-add", "target_ig": 41,
                                           "use_set": [42]},
            "predicted_assignment_delta": {"42": [29, 27]},
            "c_realizations": [{"lever": "alias", "source_object": "x",
                                "confidence_tier": "a"}],
            "surrogate_confidence": "high", "fidelity_gate": "pending"}


def _boom(**k):
    raise AssertionError("must not be called")


def test_abstain_exit3_when_g1_imperfect():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(g1_rate=0.8),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3 and "G1" in res.reason


def test_abstain_exit3_on_force_phys_collision():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(
                             reachable=False, force_phys_collision=True),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert "collision" in res.reason.lower() or "unreachable" in res.reason.lower()


def test_abstain_exit3_when_not_register_only():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(register_only=False),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


def test_abstain_exit3_on_empty_phys_target_matched_function():
    # codex major 7 / N4: matched function (empty target) ABSTAINS without
    # enumerating — never exit-4, never a fabricated candidate.
    res = solve_coloring(function="matched_fn", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(phys_target={}),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3
    assert "empty" in res.reason.lower() or "matched" in res.reason.lower()


def test_abstain_exit3_when_target_truncated():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(g1_truncated=True),
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


def test_exit0_when_actionable_candidate_found():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(candidates=[_cand()]))
    assert res.exit_code == 0
    assert res.worksheet.candidates[0]["surrogate_confidence"] == "high"


def test_exit0_when_actionable_pair_found():
    ph = {"perturbations": [{"kind": "order", "target_ig": 50,
                             "order_move": ["before", 40]},
                            {"kind": "order", "target_ig": 51,
                             "order_move": ["before", 40]}],
          "targets_met": 2, "predicted_assignment_delta": {}, "actionable": True}
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(pair_hits=[ph],
                                                        pair_ran=True))
    assert res.exit_code == 0


def test_exit4_when_no_actionable_candidate():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(
                             leads=[{"note": "no source"}], pair_ran=True))
    assert res.exit_code == 4
    assert "budget" in res.reason.lower() or "no actionable" in res.reason.lower()


def test_exit4_window_order_when_all_hits_flagged():
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: _ok_pre(),
                         enumerate_fn=lambda **k: {"enum": True},
                         realize_fn=lambda **k: _bundle(
                             window=[{"residual": "allocation-window"}]))
    assert res.exit_code == 4
    assert res.reason == "window-order"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_solve.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `solve.py`**

Create `tools/melee-agent/src/search/solver/solve.py`:

```python
"""solve_coloring — the §2 solve loop orchestrator + exit-code contract (§7).

Exit codes (verbatim, spec §7):
  0 = >=1 ACTIONABLE perturbation (resolved source object) found — an
      actionable single candidate OR an actionable pair hit (§4.1: exit-4 only
      when neither exists);
  3 = abstain: G1 imperfect / force-phys collision / target truncated /
      NOT register-only / EMPTY force-phys target (matched fn — N4; nothing to
      reach is an abstain, never a budgeted no-candidate);
  4 = no actionable perturbation <= max-perturb within frontier/cap/filter
      (budgeted no-candidate, §4.1); reason="window-order" when ALL surviving
      hits are window-order-flagged (§1.5 (c)).

Collaborators (preconditions_fn / enumerate_fn / realize_fn) are injected:
unit tests stub them; the calibration gate (Task 11) wires them to FROZEN real
artifacts through the production paths; the CLI (Task 14) wires them live.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.search.solver.worksheet import (
    FilterSummary, PairEscalation, Worksheet,
)


@dataclass
class Preconditions:
    register_only: bool
    reachable: bool
    g1_rate: float
    phys_target: dict
    g1_truncated: bool
    force_phys_collision: bool


@dataclass
class SolveResult:
    exit_code: int
    reason: str
    worksheet: Optional[Worksheet] = None


def _abstain(reason: str) -> SolveResult:
    return SolveResult(exit_code=3, reason=reason)


def solve_coloring(*, function: str, class_id: int,
                   preconditions_fn: Callable,
                   enumerate_fn: Callable,
                   realize_fn: Callable,
                   max_perturb: int = 2,
                   frontier: int = 32) -> SolveResult:
    pre = preconditions_fn(function=function, class_id=class_id)

    # §2 step 1 / §4 ABSTAIN conditions — all BEFORE any enumeration.
    if not pre.register_only:
        return _abstain("checkdiff not register-only (admit set: "
                        "operand-register-or-offset / backend-ceiling / "
                        "normalized-structural-match)")
    if not pre.phys_target:
        return _abstain("empty force-phys target (matched / no residual); "
                        "nothing to reach")
    if pre.force_phys_collision or not pre.reachable:
        return _abstain("force-phys collision: target coloring unreachable "
                        "(the escape is a structurally different virtual)")
    if pre.g1_truncated:
        return _abstain("target IG truncated/incomplete; dispense untrustworthy")
    if pre.g1_rate < 1.0:
        return _abstain(f"G1 {pre.g1_rate:.3f} < 100% on complete nodes; "
                        "what-ifs untrustworthy")

    # §2 steps 3-5: enumerate (+ escalate), then realize/rank/assemble.
    enum_out = enumerate_fn(function=function, class_id=class_id,
                            phys_target=pre.phys_target, frontier=frontier,
                            max_perturb=max_perturb)
    bundle = realize_fn(function=function, class_id=class_id,
                        enum_out=enum_out, phys_target=pre.phys_target)

    pe = bundle.pair_escalation
    worksheet = Worksheet(
        function=function, class_id=class_id, g1_rate=pre.g1_rate,
        force_phys_target={str(k): v for k, v in pre.phys_target.items()},
        reachable=pre.reachable,
        filter_summary=FilterSummary(**bundle.filter_summary),
        candidates=list(bundle.candidates),
        tooling_leads=list(bundle.tooling_leads),
        window_order=list(bundle.window_order),
        pair_escalation=PairEscalation(
            ran=pe["ran"], reason=pe["reason"],
            frontier_size=pe.get("frontier_size", 0),
            frontier=[h.get("perturbation") if isinstance(h, dict) else h
                      for h in pe.get("frontier", [])],
            pair_hits=list(pe.get("pair_hits", []))),
        enumeration_truncated=bundle.enumeration_truncated,
        evals_per_kind=dict(bundle.evals_per_kind),
    )

    actionable_pairs = [h for h in pe.get("pair_hits", [])
                        if isinstance(h, dict) and h.get("actionable")]
    if worksheet.candidates or actionable_pairs:
        return SolveResult(exit_code=0, reason="actionable candidate(s) found",
                           worksheet=worksheet)

    # §1.5 (c): ALL surviving hits window-flagged -> exit 4, reason window-order.
    if worksheet.window_order and not worksheet.candidates:
        return SolveResult(exit_code=4, reason="window-order", worksheet=worksheet)

    return SolveResult(
        exit_code=4,
        reason=(f"no actionable candidate within budget "
                f"K={max_perturb}/F={frontier}/200k + §1.5 filter"),
        worksheet=worksheet)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_solve.py -q --no-cov`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the whole solver unit suite (regression)**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/ -q --no-cov`
Expected: PASS (Tasks 1-9 suites).

- [ ] **Step 6: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/solve.py tools/melee-agent/tests/search/solver/test_solve.py && git commit -m "feat(solver): solve.py — exit 0/3/4 incl. empty-target abstain + actionable-pair exit-0 (T9)"
```

---

### Task 10: Freeze the FIVE permanent fixtures from REAL functions (live generator; codex blocker 2)

One lock-safe python generator (mirroring the order-distance plan's proven `generate.py` pattern: `swapped_tu` try/finally restore, repo build lock + `CHECKDIFF_NO_LOCK=1` for children, fresh-everything collection) freezes, per fixture: the base source, a base pcdump, the force-phys target + reachability (via the in-process `_collect_order_target_inputs`), and — for the two win fixtures — the post-win source + pcdump from git history. It also snapshots the lever catalog from the agent memory dir into the fixture tree (the calibration gate reads the SNAPSHOT so the persisted regression suite never depends on the untracked memory dir; the snapshot is later promoted to tracked D0 in Task 13).

| Fixture | Function | Base source | Post-win source |
|---|---|---|---|
| `win_cursorproc` | mnDiagram_CursorProc | `git show 'ea5da317c^1':src/melee/mn/mndiagram.c` (pre-alias, 99.52%) | `git show ea5da317c:src/melee/mn/mndiagram.c` (gp/flow-alias, 100%) |
| `win_80241e78` | mnDiagram_80241E78 | `git show 'c1aea2d0c~1':src/melee/mn/mndiagram.c` | `git show c1aea2d0c:src/melee/mn/mndiagram.c` (loop-tail data_alias + (f32)digit temp, 99.88%) |
| `reject_a_handleinput_s2` | mnDiagram_HandleInput | CURRENT worktree `src/melee/mn/mndiagram.c` (still partial) | — |
| `reject_b_80242c0c` | mnDiagram_80242C0C | CURRENT worktree `src/melee/mn/mndiagram.c` | — |
| `flag_c_createstatrow` | mnDiagram2_CreateStatRow | CURRENT worktree TU (resolve via `_find_unit_for_function`) | — |

Per-fixture frozen layout: `tests/fixtures/solver/calibration/<name>/{base.c, base.pcdump.txt, fixture.json[, post_win.c, post_win.pcdump.txt]}`. `fixture.json` schema:

```
{"name": ..., "function": ..., "unit": ..., "class_id": 0,
 "kind": "win_recovery" | "reject_confirmation",
 "checkdiff_primary": "<collector output>",
 "phys_target": {"<ig>": <reg>, ...}, "reachable": true|false,
 "expected": {"outcome": "alias_in_top8" | "rejected_a" | "rejected_b"
              | "flagged_c_exit4_window_order"},
 "alias": {"source_object_candidates": ["<acceptable source-object strings>"],
           "lever": "alias"}        # win fixtures only
}
```

Everything else (first-def opcodes, source objects, window residual, the IG) is DERIVED at test time from the frozen pcdump+source through the PRODUCTION code paths (`tb.load_ig`, `explain_virtuals`, `probe.*`) — the gate exercises the real pipeline, not recorded summaries.

**Honesty contract:** the generator ABORTS LOUDLY per fixture when a precondition fails (commit absent from history, function not in the TU, collector failure) — it never silently freezes a placeholder. Any fixture that cannot be frozen from real artifacts is reported to the orchestrator at the Task-12 checkpoint as a gate-blocking gap, not papered over. Before freezing, re-verify the three reject-fixture functions are still unmatched against FRESH upstream (`git fetch upstream`; the #2660 merge may have moved them) — substitutions are recorded in PROVENANCE.

**Files:**
- Create: `tools/melee-agent/tests/fixtures/solver/calibration/generate.py`
- Create (generated): the five fixture dirs + `catalog_snapshot/` + `FIXTURE_PROVENANCE.md`

- [ ] **Step 1: Write the generator**

Create `tools/melee-agent/tests/fixtures/solver/calibration/generate.py`:

```python
#!/usr/bin/env python3
"""Freeze the five §1.5 calibration fixtures from REAL functions.

Requires a working local mwcc-debug (`melee-agent debug dump doctor` PASSES).
Run from tools/melee-agent:

    python tests/fixtures/solver/calibration/generate.py

SAFETY CONTRACTS (mirrors the order-distance kill-switch generator):
  * every TU swap is try/finally-restored byte-exact (swapped_tu);
  * the whole run holds the repo build lock and exports CHECKDIFF_NO_LOCK=1
    AFTER our own acquisition so children/in-process collectors no-op instead
    of deadlocking;
  * collection goes through the T3 order-target collector's fresh-everything
    contract (fresh checkdiff WITH build, fresh baseline pcdump, no cache);
  * ABORT LOUDLY per fixture on any precondition failure — never freeze a
    placeholder (codex blocker 2: fixtures must be REAL function+IG+target).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent              # .../tests/fixtures/solver/calibration
AGENT_ROOT = HERE.parents[3]                        # .../tools/melee-agent
MELEE_ROOT = AGENT_ROOT.parents[1]                  # worktree root
sys.path.insert(0, str(AGENT_ROOT))

from src.search.adapters import _acquire_repo_build_lock          # noqa: E402
from src.mwcc_debug.order_target_derive import (                  # noqa: E402
    REGISTER_ONLY_PRIMARIES,
)

MEMORY_DIR = Path("/Users/mike/.claude/projects/-Users-mike-code-melee/memory")

FIXTURES = [
    dict(name="win_cursorproc", function="mnDiagram_CursorProc",
         unit="melee/mn/mndiagram", kind="win_recovery",
         base_rev="ea5da317c^1", post_rev="ea5da317c",
         alias_source_object_candidates=["gp", "flow"],
         expected="alias_in_top8"),
    dict(name="win_80241e78", function="mnDiagram_80241E78",
         unit="melee/mn/mndiagram", kind="win_recovery",
         base_rev="c1aea2d0c~1", post_rev="c1aea2d0c",
         alias_source_object_candidates=["data", "digit"],
         expected="alias_in_top8"),
    dict(name="reject_a_handleinput_s2", function="mnDiagram_HandleInput",
         unit="melee/mn/mndiagram", kind="reject_confirmation",
         base_rev=None, post_rev=None,
         alias_source_object_candidates=[], expected="rejected_a"),
    dict(name="reject_b_80242c0c", function="mnDiagram_80242C0C",
         unit="melee/mn/mndiagram", kind="reject_confirmation",
         base_rev=None, post_rev=None,
         alias_source_object_candidates=[], expected="rejected_b"),
    dict(name="flag_c_createstatrow", function="mnDiagram2_CreateStatRow",
         unit="melee/mn/mndiagram2", kind="reject_confirmation",
         base_rev=None, post_rev=None,
         alias_source_object_candidates=[],
         expected="flagged_c_exit4_window_order"),
]

# Catalog snapshot: lever entries the calibration realize step consumes.
CATALOG_SNAPSHOT = {
    "node-add": [
        {"lever": "alias", "tier": "a",
         "note": "T* a = x; route specific reads (CursorProc gp/flow-alias; "
                 "80241E78 loop-tail data_alias)"},
        {"lever": "temp-for-expr", "tier": "a",
         "note": "T t = expr; (80241E78 (f32)digit through base temp)"},
        {"lever": "anchoring", "tier": "a", "note": "second-genuine-use anchoring"},
        {"lever": "per-loop-local", "tier": "a",
         "note": "snap1/saved1, snap2/saved2 per loop"},
        {"lever": "inline-base-cast", "tier": "a",
         "note": "((CardBufEntry*)g)[i].f — NOT a cached pointer-temp"},
    ],
    "edge-add": [{"lever": "statement-hoist-sink", "tier": "b",
                  "note": "move a def/use across the other value's range"}],
    "edge-remove": [{"lever": "statement-hoist-sink", "tier": "b",
                     "note": "move a def/use across the other value's range"}],
    "order": [{"lever": "decl-reorder", "tier": "c",
               "note": "census caveat: order-only rarely byte-eliminates (0/13)"}],
}


@contextmanager
def swapped_tu(tu_path: Path, source_text: str):
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
            f"{(proc.stderr or proc.stdout or '')[-1500:]}")
    return proc


def git_show(rev: str, path: str) -> str:
    return run(["git", "show", f"{rev}:{path}"], cwd=MELEE_ROOT).stdout


def dump_pcdump(tu: Path, function: str, out: Path) -> None:
    run([sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu),
         "--function", function, "--output", str(out), "--no-cache-sync"],
        cwd=AGENT_ROOT)


def collect_target(function: str, unit: str) -> dict:
    """phys_target + reachability via the in-process order-target collector
    (fresh-everything; the TU on disk is the base being collected)."""
    import src.cli.debug as debugcli
    inputs = debugcli._collect_order_target_inputs(
        function=function, unit=unit, class_id=0,
        melee_root=MELEE_ROOT, checkdiff_timeout=120.0)
    if inputs.checkdiff_primary not in REGISTER_ONLY_PRIMARIES:
        raise SystemExit(
            f"[{function}] checkdiff primary {inputs.checkdiff_primary!r} is not "
            f"register-only — fixture precondition failed (function moved/"
            f"changed?). Re-verify against fresh upstream; do NOT freeze.")
    return {
        "checkdiff_primary": inputs.checkdiff_primary,
        "phys_target": {int(k): int(v) for k, v in inputs.phys_target.items()},
        "reachable": bool(inputs.forced_class_clean)
                     and not inputs.phys_conflicts,
    }


def process(fx: dict) -> dict:
    wdir = HERE / fx["name"]
    wdir.mkdir(parents=True, exist_ok=True)
    tu = MELEE_ROOT / "src" / f"{fx['unit']}.c"
    rel_tu = f"src/{fx['unit']}.c"

    base_src = (git_show(fx["base_rev"], rel_tu) if fx["base_rev"]
                else tu.read_text(encoding="utf-8"))
    if fx["function"] not in base_src:
        raise SystemExit(f"[{fx['name']}] {fx['function']} not in base source "
                         f"({fx['base_rev'] or 'worktree'}) — do NOT freeze.")
    (wdir / "base.c").write_text(base_src, encoding="utf-8")

    with swapped_tu(tu, base_src):
        dump_pcdump(tu, fx["function"], wdir / "base.pcdump.txt")
        target = collect_target(fx["function"], fx["unit"])

    if fx["post_rev"]:
        post_src = git_show(fx["post_rev"], rel_tu)
        (wdir / "post_win.c").write_text(post_src, encoding="utf-8")
        with swapped_tu(tu, post_src):
            dump_pcdump(tu, fx["function"], wdir / "post_win.pcdump.txt")

    record = {
        "name": fx["name"], "function": fx["function"], "unit": fx["unit"],
        "class_id": 0, "kind": fx["kind"],
        "checkdiff_primary": target["checkdiff_primary"],
        "phys_target": {str(k): v for k, v in target["phys_target"].items()},
        "reachable": target["reachable"],
        "expected": {"outcome": fx["expected"]},
        "alias": {"source_object_candidates": fx["alias_source_object_candidates"],
                  "lever": "alias"},
    }
    (wdir / "fixture.json").write_text(json.dumps(record, indent=2),
                                       encoding="utf-8")
    return record


def main() -> None:
    snap = HERE / "catalog_snapshot"
    snap.mkdir(exist_ok=True)
    for kind, entries in CATALOG_SNAPSHOT.items():
        (snap / f"{kind}.json").write_text(json.dumps(entries, indent=2),
                                           encoding="utf-8")
    results = {}
    with _acquire_repo_build_lock(MELEE_ROOT, label="solver calibration freeze"):
        os.environ["CHECKDIFF_NO_LOCK"] = "1"
        try:
            for fx in FIXTURES:
                print(f"=== {fx['name']} ===", flush=True)
                results[fx["name"]] = process(fx)
                print(json.dumps(results[fx["name"]], indent=2), flush=True)
        finally:
            os.environ.pop("CHECKDIFF_NO_LOCK", None)
    print(f"\nfroze {len(results)}/5 fixtures")
    if len(results) != 5:
        raise SystemExit("NOT all five fixtures froze — gate-blocking gap; "
                         "report to the orchestrator at the Task-12 checkpoint.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Re-verify the reject-fixture functions against FRESH upstream**

```bash
cd <WT> && git fetch upstream 2>/dev/null; for fn in mnDiagram_HandleInput mnDiagram_80242C0C mnDiagram2_CreateStatRow mnDiagram_CursorProc mnDiagram_80241E78; do printf '%-28s upstream-hits: ' "$fn"; git grep -c "$fn" upstream/master -- 'src/melee/mn/*.c' 2>/dev/null | head -1 || echo 0; done
```

Record which functions still exist where expected. If one moved/was matched upstream, substitute the nearest in-pool register-only partial of the SAME expected class and record the substitution in `FIXTURE_PROVENANCE.md` BEFORE freezing.

- [ ] **Step 3: Run the generator (live mwcc; tens of minutes)**

If `debug dump doctor` does not PASS in this worktree, run `python tools/worktree-doctor.py --fix` first.

```bash
cd <WT>/tools/melee-agent && python -m src.cli debug dump doctor 2>&1 | tail -3 && python tests/fixtures/solver/calibration/generate.py 2>&1 | tail -50
```

Expected: five per-fixture JSON records and `froze 5/5 fixtures`; `git status --porcelain src/` prints nothing (TUs restored). A loud abort on any fixture = a REAL gate-blocking gap; stop and report (do not synthesize a replacement).

- [ ] **Step 4: Write FIXTURE_PROVENANCE.md**

Create `tools/melee-agent/tests/fixtures/solver/calibration/FIXTURE_PROVENANCE.md`: per fixture — source revision (commit hash or "worktree@<HEAD sha>"), the collector outputs (checkdiff primary, phys_target size, reachable), the upstream re-verification result from Step 2, any substitutions, and the catalog-snapshot provenance (agent memory dir entries, snapshot date).

- [ ] **Step 5: Commit the generator + frozen fixtures**

```bash
cd <WT> && git add tools/melee-agent/tests/fixtures/solver/calibration/ && git commit -m "test(solver): freeze 5 REAL calibration fixtures (2 win-recovery + 3 reject-confirmation) + catalog snapshot (T10)"
```

---

### Task 11: Calibration gate — PRODUCTION `solve_coloring` over the frozen fixtures (codex blocker 2)

The persistent n≥5 regression suite: for each frozen fixture, wire `solve_coloring`'s collaborators to the FROZEN artifacts through the PRODUCTION paths — `tb.load_ig` on the frozen pcdump, `explain_virtuals` on frozen pcdump+source, `probe.derive_probe_context`/`source_object_of`/`first_def_opcode_of`/`is_window_order_residual`, `enumerate_with_escalation` (with the production pair body), `assemble_realized` with the frozen catalog snapshot — and assert the spec outcome. For the two win fixtures, additionally run the §3-style confirmation against the frozen POST-win artifacts (the alias-attributed node present in the post IG; the post commit is the recorded byte-improvement) and compute the TRUE proposal-confirmation rate (confirmed / surrogate-winning-admitted), not a proxy.

**Files:**
- Create: `tools/melee-agent/tests/search/solver/test_calibration_gate.py`

- [ ] **Step 1: Write the calibration test module**

Create `tools/melee-agent/tests/search/solver/test_calibration_gate.py`:

```python
"""§1.5 calibration gate (n>=5) — the PERSISTENT regression suite.

Runs the PRODUCTION solve_coloring over the five FROZEN real-function fixtures
(tests/fixtures/solver/calibration/<name>/), with collaborators wired to the
frozen artifacts THROUGH the production paths (load_ig / explain_virtuals /
probe / enumerate / assemble_realized). Spec §1.5: these fixtures persist as a
regression suite, NOT one-shot spike scaffolding.

Skips (with a loud reason) when the fixtures have not been generated — the
Task-12 checkpoint treats a skip as GATE NOT PASSED.
"""
import json
from pathlib import Path

import pytest

from src.mwcc_debug import tiebreak as tb
from src.mwcc_debug.virtual_attribution import explain_virtuals
from src.search.solver import probe
from src.search.solver.enumerate import EnumConfig, enumerate_with_escalation
from src.search.solver.realize import assemble_realized, load_catalog
from src.search.solver.solve import Preconditions, solve_coloring
from src.search.solver.validity import passes_1_5_filter

CAL = Path(__file__).resolve().parents[2] / "fixtures" / "solver" / "calibration"
NAMES = ["win_cursorproc", "win_80241e78", "reject_a_handleinput_s2",
         "reject_b_80242c0c", "flag_c_createstatrow"]

pytestmark = pytest.mark.skipif(
    not (CAL / "win_cursorproc" / "fixture.json").exists(),
    reason="calibration fixtures not generated (run calibration/generate.py); "
           "GATE NOT PASSED until they exist")


def _load(name):
    rec = json.loads((CAL / name / "fixture.json").read_text())
    pc = (CAL / name / "base.pcdump.txt").read_text(encoding="utf-8")
    src = (CAL / name / "base.c").read_text(encoding="utf-8")
    return rec, pc, src


def _solve(rec, pc, src):
    """Production solve over frozen artifacts (the FULL pipeline)."""
    fn, class_id = rec["function"], rec["class_id"]
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    ig = tb.load_ig(pc, fn, class_id=class_id)
    assert ig is not None, f"{rec['name']}: no COLORGRAPH in frozen dump"
    g1 = tb.validate_g1(ig, fn)
    truncated = any(n.incomplete for n in ig.nodes.values())
    win_res = probe.is_window_order_residual(ig, phys_target)

    from src.search.solver.enumerate import implicated_nodes
    impl = implicated_nodes(ig, phys_target)
    report = explain_virtuals(pc, fn, virtuals=sorted(impl),
                              source_text=src, reg_class="gpr")

    def preconditions_fn(**k):
        return Preconditions(
            register_only=True,            # frozen by the generator's collector
            reachable=rec["reachable"], g1_rate=g1.rate,
            phys_target=phys_target, g1_truncated=truncated,
            force_phys_collision=False)

    def probe_ctx_fn(p):
        return probe.derive_probe_context(
            p, ig,
            first_def_opcode=probe.first_def_opcode_of(report, p.target_ig),
            source_object=probe.source_object_of(report, p.target_ig),
            window_residual=win_res)

    def enumerate_fn(**k):
        return enumerate_with_escalation(
            ig, phys_target, config=EnumConfig(),
            filter_fn=passes_1_5_filter, probe_ctx_fn=probe_ctx_fn,
            actionable_fn=lambda hit: hit.get("actionable", False))

    def realize_fn(*, enum_out, **k):
        return assemble_realized(
            enum_out, phys_target=phys_target,
            catalog=load_catalog(CAL / "catalog_snapshot"),
            source_lookup=lambda ig_idx: probe.source_object_of(report, ig_idx))

    return solve_coloring(function=fn, class_id=class_id,
                          preconditions_fn=preconditions_fn,
                          enumerate_fn=enumerate_fn, realize_fn=realize_fn), ig, report


def _alias_rank(res, candidates_accept):
    for c in res.worksheet.candidates[:8]:
        srcs = {r["source_object"] for r in c["c_realizations"]}
        if any(any(acc in (s or "") for s in srcs) for acc in candidates_accept):
            return c["rank"]
    return None


@pytest.mark.parametrize("name", ["win_cursorproc", "win_80241e78"])
def test_win_recovery_alias_in_top8(name):
    rec, pc, src = _load(name)
    res, _ig, _report = _solve(rec, pc, src)
    assert res.exit_code == 0, f"{name}: {res.reason}"
    rank = _alias_rank(res, rec["alias"]["source_object_candidates"])
    assert rank is not None and rank <= 8, (
        f"{name}: known alias not in top-8 "
        f"(candidates={[c['c_realizations'] for c in res.worksheet.candidates[:8]]})")


@pytest.mark.parametrize("name,reason_key", [
    ("reject_a_handleinput_s2", "rejected_a"),
    ("reject_b_80242c0c", "rejected_b"),
])
def test_reject_confirmation(name, reason_key):
    rec, pc, src = _load(name)
    res, _ig, _report = _solve(rec, pc, src)
    fs = res.worksheet.filter_summary if res.worksheet else None
    assert fs is not None and getattr(fs, reason_key) > 0, (
        f"{name}: expected {reason_key} > 0 in filter_summary")


def test_flag_c_exits_window_order():
    rec, pc, src = _load("flag_c_createstatrow")
    res, _ig, _report = _solve(rec, pc, src)
    assert res.exit_code == 4 and res.reason == "window-order", res.reason
    assert res.worksheet.window_order, "window_order bucket must carry the hits"


@pytest.mark.parametrize("name", ["win_cursorproc", "win_80241e78"])
def test_implicated_1hop_contains_alias_source(name):
    # spec §2.1 open Q1: the known alias source must fall in the 1-hop set;
    # if this fails, widen EnumConfig.implicated_hops to 2 (cap 64) for this
    # function class and record the widening in FIXTURE_PROVENANCE.md.
    rec, pc, src = _load(name)
    fn = rec["function"]
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    ig = tb.load_ig(pc, fn, class_id=0)
    from src.search.solver.enumerate import implicated_nodes
    impl = implicated_nodes(ig, phys_target)
    report = explain_virtuals(pc, fn, virtuals=sorted(impl),
                              source_text=src, reg_class="gpr")
    accept = rec["alias"]["source_object_candidates"]
    found = any(
        any(acc in (probe.source_object_of(report, ig_idx) or "")
            for acc in accept)
        for ig_idx in impl)
    assert found, f"{name}: alias source outside 1-hop — widen to 2-hop (§2.1)"


@pytest.mark.parametrize("name", ["win_cursorproc", "win_80241e78"])
def test_s3_confirmation_on_post_win_artifacts(name):
    """TRUE §3-style confirmation: the alias-attributed node is PRESENT in the
    frozen POST-win IG (the post commit is the recorded byte-improvement)."""
    rec, _pc, _src = _load(name)
    post_pc = (CAL / name / "post_win.pcdump.txt").read_text(encoding="utf-8")
    post_src = (CAL / name / "post_win.c").read_text(encoding="utf-8")
    fn = rec["function"]
    post_ig = tb.load_ig(post_pc, fn, class_id=0)
    assert post_ig is not None
    report = explain_virtuals(post_pc, fn,
                              virtuals=sorted(post_ig.nodes)[:64],
                              source_text=post_src, reg_class="gpr")
    accept = rec["alias"]["source_object_candidates"]
    present = any(
        any(acc in (probe.source_object_of(report, ig_idx) or "")
            for acc in accept)
        for ig_idx in list(post_ig.nodes)[:64])
    assert present, (f"{name}: alias-attributed node NOT found in post-win IG "
                     f"— §3 confirmation failed (realization-miss)")
```

- [ ] **Step 2: Run the calibration gate**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_calibration_gate.py -q --no-cov -v 2>&1 | tail -25`
Expected: PASS on all parametrized tests (2 win-recoveries top-8, 2 reject-confirmations, 1 flag-c exit-4 window-order, 2 one-hop checks, 2 §3 confirmations). **Failures here are the gate doing its job:** a win-recovery miss → node-add encoding/probe derivation is wrong; a reject admit → filter/probe too weak; FIX (in Tasks 2-7 code, with the unit suites kept green) and re-run. If the 1-hop check fails, widen `implicated_hops` to 2 for the gate run and record it.

- [ ] **Step 3: Compute the TRUE proposal-confirmation rate**

From the Step-2 outputs: confirmation rate = (win fixtures whose §3 post-win confirmation passed) / (win fixtures whose solver run produced a surrogate-winning admitted alias). Record the number (n=2 denominator — small, stated honestly; the pilots in Task 18 extend it with live builds).

- [ ] **Step 4: Commit**

```bash
cd <WT> && git add tools/melee-agent/tests/search/solver/test_calibration_gate.py && git commit -m "test(solver): n>=5 calibration gate — PRODUCTION solve_coloring over frozen real fixtures + true §3 confirmation (T11)"
```

---

### Task 12: CHECKPOINT — calibration verdict to orchestrator (n≥5 gate, machine-checkable)

**Files:**
- Create: `docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md`

- [ ] **Step 1: Run the full Phase-0 suite one more time**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/ -q --no-cov 2>&1 | tail -5`
Expected: PASS (all unit suites + the calibration gate; the calibration module must NOT be skipping).

- [ ] **Step 2: Write the verdict doc with the machine-checkable GATE line**

Create `docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md` containing, in order: a first line that is EXACTLY `GATE: PASS` (or `GATE: FAIL — <reason>`); the per-fixture outcome table (five rows: fixture, expected, actual, pass/fail); the TRUE proposal-confirmation rate (n=2 denominator stated); the 1-hop-vs-2-hop decision; the filter_summary counts per fixture; any fixture substitutions from Task 10. **The `GATE: PASS` line may be written ONLY when all five fixtures behaved as specified** (2 win-recoveries top-8 + 3 reject-confirmations for the stated reasons) — Phase 1's mechanical preflight greps for it and fails closed.

- [ ] **Step 3: Commit**

```bash
cd <WT> && git add docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md && git commit -m "docs(solver): Phase-0 calibration verdict — machine-checkable GATE line (T12)"
```

- [ ] **Step 4: CHECKPOINT — report to orchestrator and HALT**

> **CHECKPOINT (verbatim):** "report spike verdict to orchestrator; do NOT proceed to Phase 1 without the n≥5 gate passing."

Surface to the orchestrator: the GATE line, the verdict-doc path, the per-fixture table, the true proposal-confirmation rate, the 1-hop decision, and any fixture gaps from Task 10. **Phase-1 tasks MUST NOT be dispatched (including in parallel) until the orchestrator authorizes after a `GATE: PASS`.** A `GATE: FAIL` routes back to Tasks 2-7/10 fixes — never forward.

---

## Phase 1 — driver-facing v1 (MECHANICALLY gated on Task 12)

> **Every Phase-1 task begins with the preflight (Task 13 Step 0's command).** Executors and the orchestrator must not dispatch any Phase-1 task — including in parallel — before Task 12 reports `GATE: PASS`.

### Task 13: Phase-1 mechanical preflight + D0 tracked lever catalog (BEFORE CLI wiring — codex majors 4+5)

D0 promotes the Task-10 catalog snapshot into tracked `docs/superpowers/lever-catalog/` so the shipped CLI default reads tracked data (rev3 §7: D0 is post-calibration but REQUIRED before the driver-wiring milestone). The mechanical preflight makes the Phase-0 gate fail-closed.

**Files:**
- Create: `docs/superpowers/lever-catalog/{node-add,edge-add,edge-remove,order}.json` + `README.md`
- Create: `tools/melee-agent/tests/search/solver/test_catalog_dir.py`

- [ ] **Step 0: MECHANICAL GATE CHECK (run first in EVERY Phase-1 task)**

```bash
cd <WT> && grep -qx 'GATE: PASS' docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md && echo 'PHASE-1 PREFLIGHT: OK' || { echo 'PHASE-1 PREFLIGHT FAILED: calibration GATE not PASS — STOP (do not proceed)'; exit 1; }
```

Expected: `PHASE-1 PREFLIGHT: OK`. On failure: STOP and report to the orchestrator; no Phase-1 work may proceed.

- [ ] **Step 1: Promote the catalog snapshot to the tracked D0 dir**

```bash
cd <WT> && mkdir -p docs/superpowers/lever-catalog && cp tools/melee-agent/tests/fixtures/solver/calibration/catalog_snapshot/*.json docs/superpowers/lever-catalog/ && ls docs/superpowers/lever-catalog/
```

Expected: `node-add.json edge-add.json edge-remove.json order.json` present.

- [ ] **Step 2: Write the failing tracked-catalog test**

Create `tools/melee-agent/tests/search/solver/test_catalog_dir.py`:

```python
from pathlib import Path

from src.search.solver.realize import load_catalog

# tools/melee-agent/tests/search/solver/test_catalog_dir.py
# parents: [0]=solver [1]=search [2]=tests [3]=tools/melee-agent [4]=tools [5]=<WT>
CATALOG_DIR = (Path(__file__).resolve().parents[5]
               / "docs" / "superpowers" / "lever-catalog")


def test_tracked_catalog_dir_resolves():
    assert CATALOG_DIR.is_dir(), f"D0 catalog dir missing: {CATALOG_DIR}"


def test_tracked_catalog_loads_with_priority_order():
    cat = load_catalog(CATALOG_DIR)
    assert cat["node-add"][0]["lever"] == "alias"
    assert all(e["tier"] == "a" for e in cat["node-add"])
    assert cat["edge-add"][0]["tier"] == "b"
    assert cat["edge-remove"][0]["tier"] == "b"
    assert cat["order"][0]["tier"] == "c"
```

- [ ] **Step 3: Run to verify it passes**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_catalog_dir.py -q --no-cov`
Expected: PASS (2 tests). If the `parents[5]` resolution fails, the FIRST test names the resolved path — fix the index against the printed path, never hand-wave.

- [ ] **Step 4: Write the README + commit**

Create `docs/superpowers/lever-catalog/README.md` noting: the per-kind JSON format consumed by `realize.load_catalog`; provenance (promoted from the calibration snapshot, originally curated from the agent-memory lever entries `accessor_macro_inline_frame_lever`, `comma_expr_defeats_licm_hoist`, `mndiagram_levers_and_walls`, `mndiagram_inputproc_simplify_tiebreak`, `dispform_inline_base_cast_and_per_loop_locals`, `call_shape_and_fmadds_operand_levers`); and that the CLI `--catalog-dir` defaults here.

```bash
cd <WT> && git add docs/superpowers/lever-catalog/ tools/melee-agent/tests/search/solver/test_catalog_dir.py && git commit -m "feat(solver): D0 — tracked lever catalog promoted from calibration snapshot, before CLI wiring (T13)"
```

---

### Task 14: CLI `debug solve coloring` — `solve_app` + REAL live probe wiring (codex blocker 3)

Define `solve_app`, wire `debug_app.add_typer(solve_app, name="solve")` (after `__init__.py:1971`), register `@solve_app.command("coloring")` with the spec §7 signature, and implement the live collaborators with the PRODUCTION probe derivation — the live `probe_ctx_fn` is built by a testable module-level factory that derives all four signals from `explain_virtuals` + the IG + the window-residual classifier (never hardcoded). `--kinds` accepts the advertised default `node-add,edge,order` and normalizes via `normalize_kinds` (codex major 6). `--catalog-dir` defaults to the tracked D0 dir (exists since Task 13).

**CLI signature (verbatim, spec §7):**
`debug solve coloring -f FN [--class gpr|fpr] [--pcdump P] [--max-perturb 2] [--frontier 32] [--kinds node-add,edge,order] [--experimental-kinds coalesce] [--catalog-dir DIR] [--json]`

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Create: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_cli_solve.py`:

```python
import json

from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.solve import SolveResult
from src.search.solver.worksheet import (
    FilterSummary, PairEscalation, Worksheet,
)

runner = CliRunner()


def _ws():
    return Worksheet(
        function="mnDiagram_80241E78", class_id=0, g1_rate=1.0,
        force_phys_target={"42": 27}, reachable=True,
        filter_summary=FilterSummary(4, 0, 0, 0, 0),
        candidates=[{"rank": 1,
                     "perturbation": {"kind": "node-add", "target_ig": 41,
                                      "use_set": [42]},
                     "predicted_assignment_delta": {},
                     "c_realizations": [{"lever": "alias",
                                         "source_object": "data_alias",
                                         "confidence_tier": "a"}],
                     "surrogate_confidence": "high",
                     "fidelity_gate": "pending"}],
        tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(False, "actionable single exists", 0, [], []),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 4, "edge": 0, "order": 0})


def test_solve_coloring_exit0_and_json(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=0, reason="ok", worksheet=_ws()))
    result = runner.invoke(debugcli.debug_app, [
        "solve", "coloring", "-f", "mnDiagram_80241E78", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["function"] == "mnDiagram_80241E78"
    assert payload["candidates"][0]["surrogate_confidence"] == "high"


def test_solve_coloring_abstain_exit3(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=3, reason="G1 0.800 < 100%"))
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 3, result.output
    assert "G1" in result.output


def test_solve_coloring_exit4(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=4, reason="window-order",
                                 worksheet=_ws()))
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 4, result.output


def test_solve_coloring_passes_kinds_and_catalog_default(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return SolveResult(exit_code=4, reason="x", worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake)
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 4
    assert seen["kinds"] == ["node-add", "edge", "order"]   # advertised default
    assert str(seen["catalog_dir"]).endswith("docs/superpowers/lever-catalog")


def test_solve_app_registered():
    assert "coloring" in [c.name for c in debugcli.solve_app.registered_commands]
    assert "solve" in [g.name for g in debugcli.debug_app.registered_groups]


# --- the live probe adapter factory (codex blocker 3: all four keys derived) ---
def test_live_probe_ctx_factory_derives_all_four_keys():
    class _FD:
        opcode = "li"
    class _SrcConst:
        name = "zero"; expression = None; first_def = _FD()
    class _SrcRuntime:
        name = "row"; expression = None; first_def = None
    class _VA:
        def __init__(self, ig_idx, source):
            self.ig_idx = ig_idx; self.source = source
    class _Report:
        virtuals = (_VA(41, _SrcConst()), _VA(42, _SrcRuntime()), _VA(43, None))

    nodes = {
        41: IGNode(41, {42, 43}, {}, 2, False, 22),
        42: IGNode(42, {41}, {}, 1, False, 21),
        43: IGNode(43, {41}, {}, 1, False, 20),
    }
    ig = IG(class_id=0, select_order=[41, 42, 43], nodes=nodes,
            decision_igs={41, 42, 43})
    from src.search.solver.types import Perturbation, PerturbationKind

    # window_residual True for this target ({41: 21} — 22->21 callee shift).
    fn = debugcli._solver_probe_ctx_factory(ig, _Report(), {41: 21})
    ctx_const = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=41,
                                use_set=(42,), new_ig=100, position="after",
                                interfere_original=True))
    assert ctx_const.is_runtime_value is False          # li-defined (L2a)
    assert ctx_const.copy_already_survives is True      # window residual (L2c)
    ctx_nosrc = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=43,
                                use_set=(41,), new_ig=101, position="after",
                                interfere_original=True))
    assert ctx_nosrc.caller_visible_source is False     # source None (L2b)
    ctx_bait = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=41,
                               use_set=(42, 43), new_ig=102, position="after",
                               interfere_original=True))
    assert ctx_bait.original_keeps_use_past_vprime is False   # all uses (L1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_cli_solve.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'src.cli.debug' has no attribute 'solve_app'` (and `_solver_probe_ctx_factory`).

- [ ] **Step 3: Define + wire `solve_app` and the live helpers**

In `tools/melee-agent/src/cli/debug/__init__.py`:

(a) After the `util_app = typer.Typer(...)` definition (ends line 1962), add:

```python
solve_app = typer.Typer(
    help="Inverse-coloring solver: surrogate-checked, §1.5-filtered C-move "
         "worksheets for register-only residuals."
)
```

(b) In the `add_typer` block (after line 1971 `debug_app.add_typer(util_app, name="util")`), add:

```python
debug_app.add_typer(solve_app, name="solve")
```

(c) Insert the live helpers + the command just BEFORE `@inspect_app.command(name="explain-diff")` (line 22117):

```python
def _solver_probe_ctx_factory(ig, report, phys_target):
    """Build the live probe_ctx_fn from PRODUCTION derivations (codex blocker
    3): first-def opcode + source object from the explain_virtuals report,
    window residual from the classifier, survival from the strict-subset rule
    inside derive_probe_context. Unit-tested directly; never hardcoded."""
    from src.search.solver import probe as solver_probe

    win_res = solver_probe.is_window_order_residual(ig, phys_target)

    def probe_ctx_fn(p):
        return solver_probe.derive_probe_context(
            p, ig,
            first_def_opcode=solver_probe.first_def_opcode_of(report, p.target_ig),
            source_object=solver_probe.source_object_of(report, p.target_ig),
            window_residual=win_res)
    return probe_ctx_fn


def _run_solve_coloring(*, function: str, class_id: int, pcdump,
                        max_perturb: int, frontier: int, kinds: list,
                        experimental_kinds: list, catalog_dir):
    """Live collaborator wiring for solve_coloring. Monkeypatched in unit
    tests; exercised at the Task-18 pilots."""
    from src.mwcc_debug import tiebreak as tb
    from src.mwcc_debug.order_target_derive import REGISTER_ONLY_PRIMARIES
    from src.mwcc_debug.virtual_attribution import explain_virtuals
    from src.search.solver import probe as solver_probe
    from src.search.solver.enumerate import (
        EnumConfig, enumerate_with_escalation, implicated_nodes,
    )
    from src.search.solver.realize import assemble_realized, load_catalog
    from src.search.solver.solve import Preconditions, solve_coloring
    from src.search.solver.validity import passes_1_5_filter

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text(encoding="utf-8")
    tu_c = melee_root / "src" / f"{unit}.c" if unit else None
    source_text = tu_c.read_text(encoding="utf-8") if tu_c and tu_c.exists() else ""

    inputs = _collect_order_target_inputs(
        function=function, unit=unit, class_id=class_id,
        melee_root=melee_root, checkdiff_timeout=120.0)
    phys_target = {int(k): int(v) for k, v in inputs.phys_target.items()}
    ig = tb.load_ig(pcdump_text, function, class_id=class_id)
    g1 = tb.validate_g1(ig, function) if ig else None
    truncated = bool(ig and any(n.incomplete for n in ig.nodes.values()))

    report = None
    if ig is not None and phys_target:
        impl = implicated_nodes(ig, phys_target)
        report = explain_virtuals(
            pcdump_text, function, virtuals=sorted(impl),
            source_text=source_text,
            reg_class="fp" if class_id == 1 else "gpr")

    def preconditions_fn(**k):
        return Preconditions(
            register_only=inputs.checkdiff_primary in REGISTER_ONLY_PRIMARIES,
            reachable=bool(getattr(inputs, "forced_class_clean", False))
                      and not inputs.phys_conflicts,
            g1_rate=(g1.rate if g1 else 0.0),
            phys_target=phys_target,
            g1_truncated=truncated,
            force_phys_collision=bool(inputs.phys_conflicts))

    def enumerate_fn(**k):
        cfg = EnumConfig(frontier=frontier)
        return enumerate_with_escalation(
            ig, phys_target, config=cfg, filter_fn=passes_1_5_filter,
            probe_ctx_fn=_solver_probe_ctx_factory(ig, report, phys_target),
            actionable_fn=lambda hit: hit.get("actionable", False))

    def realize_fn(*, enum_out, **k):
        return assemble_realized(
            enum_out, phys_target=phys_target,
            catalog=load_catalog(catalog_dir),
            source_lookup=lambda ig_idx: solver_probe.source_object_of(report,
                                                                       ig_idx))

    # kinds/experimental_kinds: the advertised default is the full default set;
    # a non-default --kinds restricts enumeration (see the note below).
    return solve_coloring(function=function, class_id=class_id,
                          preconditions_fn=preconditions_fn,
                          enumerate_fn=enumerate_fn, realize_fn=realize_fn,
                          max_perturb=max_perturb, frontier=frontier)
```

> When `--kinds` is non-default, pass it through to enumeration by adding a `kinds=` passthrough parameter to `enumerate_with_escalation` (forwarded to `enumerate_single`, which already accepts `kinds`) and setting `kinds=tuple(kinds)` inside `enumerate_fn` — a 3-line change; add an assertion to the T5 tests when exercised.

(d) The command:

```python
@solve_app.command("coloring")
def solve_coloring_cmd(
    function: Annotated[str, typer.Option("--function", "-f")],
    register_class: Annotated[str, typer.Option(
        "--class", help="Register class: gpr (default) or fpr.")] = "gpr",
    pcdump: Annotated[Optional[Path], typer.Option("--pcdump")] = None,
    max_perturb: Annotated[int, typer.Option("--max-perturb")] = 2,
    frontier: Annotated[int, typer.Option("--frontier")] = 32,
    kinds: Annotated[str, typer.Option(
        "--kinds", help="Enumerated kinds (advertised vocabulary; 'edge' "
        "expands to edge-add+edge-remove).")] = "node-add,edge,order",
    experimental_kinds: Annotated[str, typer.Option(
        "--experimental-kinds", help="e.g. coalesce (spec §1d).")] = "",
    catalog_dir: Annotated[Optional[Path], typer.Option(
        "--catalog-dir",
        help="Lever catalog dir (default: the tracked D0 catalog).")] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inverse register coloring: enumerate §1.5-filtered node-set/content
    perturbations, predict their coloring with the SELECT surrogate, map
    winners to C moves, emit a ranked worksheet. Exit 0=actionable candidate,
    3=abstain, 4=budgeted no-candidate (incl. window-order)."""
    from ...mwcc_debug import tiebreak as tb

    resolved_catalog = catalog_dir or (
        DEFAULT_MELEE_ROOT / "docs" / "superpowers" / "lever-catalog")
    res = _run_solve_coloring(
        function=function, class_id=tb.parse_register_class(register_class),
        pcdump=pcdump, max_perturb=max_perturb, frontier=frontier,
        kinds=[k.strip() for k in kinds.split(",") if k.strip()],
        experimental_kinds=[k.strip() for k in experimental_kinds.split(",")
                            if k.strip()],
        catalog_dir=resolved_catalog)
    if res.worksheet is not None and json_out:
        print(res.worksheet.to_json())
    elif res.worksheet is not None:
        ws = res.worksheet
        typer.echo(f"solve {ws.function}: class {ws.class_id} "
                   f"G1 {ws.g1_rate*100:.1f}% reachable={ws.reachable} -> "
                   f"{len(ws.candidates)} actionable, "
                   f"{len(ws.tooling_leads)} tooling-lead(s), "
                   f"{len(ws.window_order)} window-order, "
                   f"pairs={'ran' if ws.pair_escalation.ran else 'skipped'}")
        for c in ws.candidates:
            typer.echo(f"  #{c['rank']} [{c['surrogate_confidence']}] "
                       f"{c['perturbation']['kind']} ig{c['perturbation']['target_ig']} -> "
                       f"{[r['lever'] for r in c['c_realizations']]}")
    if not json_out and res.reason:
        typer.echo(f"reason: {res.reason}")
    raise typer.Exit(res.exit_code)
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_cli_solve.py -q --no-cov`
Expected: PASS (6 tests).

- [ ] **Step 5: Verify the legacy sibling was NOT touched + the CLI imports clean**

Run: `cd <WT> && git status --porcelain tools/melee-agent/src/cli/debug.py && cd tools/melee-agent && python -c "import src.cli.debug as d; print('coloring' in [c.name for c in d.solve_app.registered_commands], 'solve' in [g.name for g in d.debug_app.registered_groups])"`
Expected: first command prints NOTHING; second prints `True True`.

- [ ] **Step 6: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/search/solver/test_cli_solve.py && git commit -m "feat(cli): debug solve coloring — solve_app + REAL live probe wiring + tracked-catalog default (T14)"
```

---

### Task 15: Negative controls N4-N7 — incl. the pair-FOUND assertion (codex blocker 1 + minor 11)

N4/N5 are regressions of the Task-9 abstain guards (kept as named controls); N6 exercises the §3 gate; **N7 derives a pair-only fixture, brute-force-confirms no single reaches the target with the PRODUCTION enumerator, and asserts the production pair composition FINDS the recorded working pair** — not merely that escalation ran.

**N7 construction (finding rev2-7):** PRIMARY = derive from the real `fn_803ACD58` decl-chain IG (live-extract its IG + a working pair under the lock contract if the worktree supports it). FALLBACK = the VERIFIED synthetic pair-only construction from Task 5 (`_pair_only_ig`: two targets {50:3, 51:3}, each blocked by both r3-holders; no single meets both — already brute-force-confirmed by the T5 exhaustive test), frozen to JSON with the same no-single confirmation required. Either way `PROVENANCE.md` records which path was taken and the recorded `working_pair`.

**Files:**
- Create: `tools/melee-agent/tests/fixtures/solver/n7_pair/n7_ig.json`
- Create: `tools/melee-agent/tests/fixtures/solver/n7_pair/PROVENANCE.md`
- Create: `tools/melee-agent/tests/search/solver/test_negative_controls.py`

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Author the N7 fixture**

Attempt the PRIMARY derivation (extract `fn_803ACD58`'s class-0 IG via `debug dump local` on `src/sysdolphin/baselib/hsd_3AA7.c` under the lock contract; identify a working pair from the decl-chain history; brute-force-confirm). If extraction is not clean (function shape changed, dump truncated), use the FALLBACK synthetic construction. Write `tools/melee-agent/tests/fixtures/solver/n7_pair/n7_ig.json`:

```json
{
  "function": "fn_803ACD58_or_synthetic",
  "class_id": 0,
  "ig": {
    "select_order": [40, 41, 50, 51],
    "nodes": {
      "40": {"neighbors": [0, 50, 51], "precolored": {"0": 0}, "array_size": 3,
              "incomplete": false, "observed_reg": 3},
      "41": {"neighbors": [0, 50, 51], "precolored": {"0": 0}, "array_size": 3,
              "incomplete": false, "observed_reg": 3},
      "50": {"neighbors": [0, 40, 41], "precolored": {"0": 0}, "array_size": 3,
              "incomplete": false, "observed_reg": 4},
      "51": {"neighbors": [0, 40, 41], "precolored": {"0": 0}, "array_size": 3,
              "incomplete": false, "observed_reg": 4}
    }
  },
  "phys_target": {"50": 3, "51": 3},
  "expected": {
    "no_single_reaches": true,
    "working_pair": [{"kind": "order", "target_ig": 50},
                      {"kind": "order", "target_ig": 51}]
  }
}
```

(The JSON above is the verified FALLBACK; the PRIMARY derivation replaces the `ig`/`phys_target`/`working_pair` content with the real extraction and updates `function`.)

- [ ] **Step 2: Write the failing tests**

Create `tools/melee-agent/tests/search/solver/test_negative_controls.py`:

```python
import json
from pathlib import Path

from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.enumerate import (
    EnumConfig, enumerate_single, enumerate_with_escalation,
)
from src.search.solver.gate import classify_fidelity
from src.search.solver.solve import Preconditions, solve_coloring
from src.search.solver.validity import FilterVerdict

# tests/search/solver/... -> parents[2] == tests/ (codex minor 11 path fix)
N7 = (Path(__file__).resolve().parents[2]
      / "fixtures" / "solver" / "n7_pair" / "n7_ig.json")


def _boom(**k):
    raise AssertionError("must not be called")


# --- N4: matched function (empty phys_target) -> exit-3, never enumerates ---
def test_n4_matched_function_abstains_exit3():
    pre = Preconditions(register_only=True, reachable=True, g1_rate=1.0,
                        phys_target={}, g1_truncated=False,
                        force_phys_collision=False)
    res = solve_coloring(function="matched_fn", class_id=0,
                         preconditions_fn=lambda **k: pre,
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


# --- N5: shuffled/unreachable target (collision) -> exit-3, never enumerates ---
def test_n5_shuffled_target_collision_abstains_exit3():
    pre = Preconditions(register_only=True, reachable=False, g1_rate=1.0,
                        phys_target={42: 27}, g1_truncated=False,
                        force_phys_collision=True)
    res = solve_coloring(function="f", class_id=0,
                         preconditions_fn=lambda **k: pre,
                         enumerate_fn=_boom, realize_fn=_boom)
    assert res.exit_code == 3


# --- N6: wrong/no-op alias on a known win -> never a confirmed win ---
def test_n6_wrong_alias_is_realization_miss():
    out = classify_fidelity(new_ig=99, perturbation_present=False, g1_rate=1.0,
                            predicted={99: 27}, actual={}, phys_target={99: 27},
                            no_op=False)
    assert out.classification == "realization-miss" and out.is_win is False


def test_n6_noop_alias_is_unattributed():
    out = classify_fidelity(new_ig=99, perturbation_present=False, g1_rate=1.0,
                            predicted={}, actual={}, phys_target={99: 27},
                            no_op=True)
    assert out.classification == "UNATTRIBUTED" and out.is_win is False


# --- N7: pair-only fixture — brute-force no-single + pair FOUND ---
def _build_ig(rec):
    nodes = {int(k): IGNode(int(k), set(n["neighbors"]),
                            {int(a): b for a, b in (n.get("precolored") or {}).items()},
                            n["array_size"], n["incomplete"], n["observed_reg"])
             for k, n in rec["ig"]["nodes"].items()}
    return IG(class_id=rec["class_id"],
              select_order=list(rec["ig"]["select_order"]),
              nodes=nodes, decision_igs=set(nodes))


def _admit_all(p, ctx):
    return FilterVerdict(admit=True)


def test_n7_no_single_reaches_target_brute_force():
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    big = EnumConfig(eval_cap=10_000_000, edge_floor=4_000_000,
                     order_floor=4_000_000)
    res = enumerate_single(ig, phys_target, config=big, filter_fn=_admit_all,
                           probe_ctx_fn=lambda p: None)
    assert res.full_hits == [], "N7 fixture is secretly single-solvable — re-derive"
    assert res.partial_hits, "frontier must be non-empty for pair composition"


def test_n7_escalation_fires_and_FINDS_the_working_pair():
    # codex blocker 1: not "the callback ran" — the production composition must
    # FIND the recorded working pair within frontier/cap.
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}
    out = enumerate_with_escalation(
        ig, phys_target, config=EnumConfig(), filter_fn=_admit_all,
        probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False))
    pe = out["pair_escalation"]
    assert pe["ran"] is True
    assert pe["pair_hits"], "production pair composition found no pair"
    expected = {(e["kind"], e["target_ig"])
                for e in rec["expected"]["working_pair"]}
    found = any(
        {(p.kind.value, p.target_ig) for p in hit["perturbations"]} == expected
        for hit in pe["pair_hits"])
    assert found, (f"recorded working pair {sorted(expected)} not among "
                   f"pair_hits")
    assert pe["truncated"] is False                       # respected the cap


def test_n7_low_confidence_single_does_not_suppress_pairs():
    # finding 3 regression: a FULL but non-actionable single must not gate pairs.
    rec = json.loads(N7.read_text())
    ig = _build_ig(rec)
    phys_target = {int(k): v for k, v in rec["phys_target"].items()}

    from src.search.solver.enumerate import EnumResult, compose_frontier_pairs

    def single_with_lead(*a, **k):
        real = enumerate_single(ig, phys_target, config=EnumConfig(),
                                filter_fn=_admit_all,
                                probe_ctx_fn=lambda p: None)
        fake_full = [{"perturbation": real.partial_hits[0]["perturbation"],
                      "targets_met": len(phys_target), "delta": {},
                      "actionable": False}]          # tooling-lead-shaped
        return EnumResult(fake_full, real.partial_hits, [], real.filter_counts,
                          real.evals_per_kind, False, "order")

    out = enumerate_with_escalation(
        ig, phys_target, config=EnumConfig(), filter_fn=_admit_all,
        probe_ctx_fn=lambda p: None,
        actionable_fn=lambda hit: hit.get("actionable", False),
        _single_impl=single_with_lead, _pair_impl=compose_frontier_pairs)
    assert out["pair_escalation"]["ran"] is True
```

- [ ] **Step 3: Run to verify they pass (re-derive the fixture on a no-single failure)**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_negative_controls.py -q --no-cov`
Expected: PASS (7 tests). A `no_single_reaches` failure means the fixture is secretly single-solvable (the rev2-7 trap) — re-derive/adjust and re-run.

- [ ] **Step 4: Write the N7 PROVENANCE.md + commit**

Create `tools/melee-agent/tests/fixtures/solver/n7_pair/PROVENANCE.md` recording: PRIMARY (real `fn_803ACD58` extraction) vs FALLBACK (verified synthetic) path taken, the recorded working pair, and the brute-force no-single confirmation command/output.

```bash
cd <WT> && git add tools/melee-agent/tests/search/solver/test_negative_controls.py tools/melee-agent/tests/fixtures/solver/n7_pair/ && git commit -m "test(solver): negative controls N4-N7 — pair-only fixture with brute-force no-single + pair-FOUND assertion (T15)"
```

---

### Task 16: Convert `suggest register-tiebreak` to a thin caller of `solve coloring`

Spec §7 (DECISION, was open Q6): `suggest register-tiebreak` BECOMES a thin caller of `solve coloring` so there are not two diverging lever vocabularies.

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py` (the existing handler, ~line 19449)
- Create: `tools/melee-agent/tests/search/solver/test_suggest_thin_caller.py`

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Locate + read the existing handler**

Run: `cd <WT>/tools/melee-agent && grep -n "register-tiebreak\|def suggest_register_tiebreak\|@suggest_app.command" src/cli/debug/__init__.py | head`
Read the handler's signature + body so the conversion preserves its CLI surface (`--function`/`-f`, `--class`) while delegating.

- [ ] **Step 2: Write the failing test**

Create `tools/melee-agent/tests/search/solver/test_suggest_thin_caller.py`:

```python
from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.search.solver.solve import SolveResult
from src.search.solver.worksheet import FilterSummary, PairEscalation, Worksheet

runner = CliRunner()


def _ws():
    return Worksheet(
        function="f", class_id=0, g1_rate=1.0, force_phys_target={},
        reachable=True, filter_summary=FilterSummary(0, 0, 0, 0, 0),
        candidates=[], tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(False, "x", 0, [], []),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 0, "edge": 0, "order": 0})


def test_suggest_register_tiebreak_delegates_to_solve(monkeypatch):
    called = {"n": 0}

    def fake_solve(**kw):
        called["n"] += 1
        return SolveResult(exit_code=4, reason="no actionable candidate",
                           worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake_solve)
    result = runner.invoke(debugcli.debug_app,
                           ["suggest", "register-tiebreak", "-f", "f"])
    assert called["n"] == 1, "suggest register-tiebreak did not delegate"
    assert result.exit_code == 4
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_suggest_thin_caller.py -q --no-cov`
Expected: FAIL (`called["n"] == 0` — the heuristic body does not delegate).

- [ ] **Step 4: Convert the handler**

Rewrite the `suggest register-tiebreak` handler body to call `_run_solve_coloring(...)` with its existing `--function`/`--class` options mapped (defaults: `max_perturb=2`, `frontier=32`, advertised kinds, tracked catalog dir), print the worksheet summary, and `raise typer.Exit(res.exit_code)`. Keep its options so callers don't break; help text notes it now delegates to `solve coloring`.

- [ ] **Step 5: Run to verify it passes + no legacy sibling touched**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_suggest_thin_caller.py -q --no-cov && cd <WT> && git status --porcelain tools/melee-agent/src/cli/debug.py`
Expected: PASS; the `git status` prints nothing.

- [ ] **Step 6: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/tests/search/solver/test_suggest_thin_caller.py && git commit -m "refactor(cli): suggest register-tiebreak delegates to solve coloring (T16, spec §7 Q6)"
```

---

### Task 17: FPR G1 sweep — STRICT classifier + COMPLETE live driver (codex major 8)

Rev3 §5's contract, encoded strictly: `pass` (0 clean-fixture misses) / `proceed_filtered` (EVERY miss covered by a documented static exclusion, `fpr_coverage: filtered`) / `hard_stop` (ANY uncharacterized clean-fixture miss — "do not relax"). The `hard_stop` remedy field distinguishes rev3's two outcomes: uncharacterized rate ≤5% → `fix-fpr-dispense-reading` (fix and re-run); >5% → `ship-gpr-only`. Either way the FPR pilot is BLOCKED until a re-run passes. The live driver is fully specified: functions come from the build report (schema probed first), each is dumped under the lock contract, class-1 sections tallied.

**Files:**
- Create: `tools/melee-agent/src/search/solver/fpr_sweep.py`
- Create: `tools/melee-agent/tests/search/solver/test_fpr_sweep.py`
- Create (generated): `docs/superpowers/results/2026-06-12-surrogate-solver-fpr-sweep.md`

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Write the failing classifier tests**

Create `tools/melee-agent/tests/search/solver/test_fpr_sweep.py`:

```python
from src.search.solver.fpr_sweep import SweepTally, classify_sweep


def test_zero_misses_is_pass():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=100, g1_imperfect_clean=0,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "pass" and v["fpr_coverage"] == "full"
    assert v["n_fpr"] == 120 and v["denominator_clean"] == 100


def test_all_characterized_misses_proceed_filtered():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=92, g1_imperfect_clean=8,
                   characterized_exclusions=8)
    v = classify_sweep(t)
    assert v["verdict"] == "proceed_filtered" and v["fpr_coverage"] == "filtered"


def test_any_uncharacterized_miss_is_hard_stop_even_below_5pct():
    # codex major 8: rev3 §5 — a clean fixture NOT covered by a documented
    # static exclusion is a HARD STOP ("do not relax"), even at 1%.
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=99, g1_imperfect_clean=1,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop"
    assert v["remedy"] == "fix-fpr-dispense-reading"     # <=5%: fix and re-run


def test_uncharacterized_above_5pct_ships_gpr_only():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=90, g1_imperfect_clean=10,
                   characterized_exclusions=0)
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop" and v["remedy"] == "ship-gpr-only"


def test_partially_characterized_is_still_hard_stop():
    t = SweepTally(n_fpr=120, clean=100, excluded_truncated=20,
                   g1_perfect=94, g1_imperfect_clean=6,
                   characterized_exclusions=4)        # 2 uncharacterized
    v = classify_sweep(t)
    assert v["verdict"] == "hard_stop"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_fpr_sweep.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Probe the build-report schema (the deterministic input source)**

```bash
cd <WT> && python -c "
import json; from pathlib import Path
p = Path('build/GALE01/report.json')
print('exists:', p.exists())
d = json.loads(p.read_text())
print('top keys:', sorted(d)[:10])
u = (d.get('units') or [None])[0]
print('unit keys:', sorted(u) if isinstance(u, dict) else u)
fns = (u or {}).get('functions') or [None]
print('fn keys:', sorted(fns[0]) if isinstance(fns[0], dict) else fns[0])
"
```

Record the exact key names for: unit name, function name, and the match metric (expected objdiff shape: `units[].functions[]` with `fuzzy_match_percent`). If keys differ from the implementation below, adjust the TWO accessor lines in `_iter_matched_functions` to the printed names before Step 4.

- [ ] **Step 4: Implement `fpr_sweep.py` (classifier + COMPLETE live driver)**

Create `tools/melee-agent/src/search/solver/fpr_sweep.py`:

```python
"""FPR G1 sweep (spec §5) — STAGED: sizing -> clean-fixture gate -> time-boxed
fallback. classify_sweep is PURE; run_fpr_sweep is the COMPLETE live driver.

STRICT contract (codex major 8 / rev3 §5 "do not relax"):
  pass             : zero G1 misses on clean class-1 fixtures.
  proceed_filtered : EVERY miss covered by a documented static exclusion
                     (fpr_coverage: filtered).
  hard_stop        : ANY uncharacterized clean-fixture miss. remedy:
                     "fix-fpr-dispense-reading" when the uncharacterized rate
                     is <= 5% (fix the dispense reading, re-run);
                     "ship-gpr-only" when > 5%. Both BLOCK the FPR pilot.

Live driver inputs (deterministic): the objdiff build report
(build/GALE01/report.json — schema probed in the plan's Step 3), iterated for
matched (100%) functions; each is dumped via `debug dump local --no-cache-sync`
under the caller-held repo lock (CHECKDIFF_NO_LOCK=1 children contract), and
its class-1 COLORGRAPH (if any) is G1-validated.
Run:  python -m src.search.solver.fpr_sweep [--limit N]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SweepTally:
    n_fpr: int                       # SIZING: class-1-COLORGRAPH-bearing matched fns
    clean: int                       # untruncated + complete-interferer fixtures
    excluded_truncated: int          # un-gradeable (excluded from denominator)
    g1_perfect: int
    g1_imperfect_clean: int
    characterized_exclusions: int    # misses explained by a documented static property


def classify_sweep(t: SweepTally) -> dict:
    base = {"n_fpr": t.n_fpr, "denominator_clean": t.clean,
            "excluded_truncated": t.excluded_truncated,
            "g1_perfect": t.g1_perfect,
            "g1_imperfect_clean": t.g1_imperfect_clean,
            "characterized_exclusions": t.characterized_exclusions}
    if t.g1_imperfect_clean == 0:
        return {**base, "verdict": "pass", "fpr_coverage": "full"}
    uncharacterized = t.g1_imperfect_clean - t.characterized_exclusions
    if uncharacterized <= 0:
        return {**base, "verdict": "proceed_filtered",
                "fpr_coverage": "filtered"}
    rate = uncharacterized / max(t.clean, 1)
    return {**base, "verdict": "hard_stop", "fpr_coverage": "gpr_only",
            "uncharacterized": uncharacterized, "uncharacterized_rate": rate,
            "remedy": "ship-gpr-only" if rate > 0.05
                      else "fix-fpr-dispense-reading"}


def _iter_matched_functions(report: dict):
    """Yield (unit_name, function_name) for 100%-matched functions.
    Accessor lines adjusted to the Step-3 schema probe if needed."""
    for unit in report.get("units", []):
        uname = unit.get("name", "")
        for fn in unit.get("functions", []):
            pct = fn.get("fuzzy_match_percent")          # accessor line 1
            name = fn.get("name")                        # accessor line 2
            if name and pct is not None and float(pct) >= 100.0:
                yield uname, name


def run_fpr_sweep(*, melee_root: Path, limit: int | None = None,
                  exclusion_predicates: dict | None = None) -> dict:
    """COMPLETE live sweep. exclusion_predicates: {label: fn(ig)->bool} — the
    documented static properties that characterize a miss (starts empty; add
    one ONLY with a written justification in the sweep doc)."""
    sys.path.insert(0, str(melee_root / "tools" / "melee-agent"))
    from src.mwcc_debug import tiebreak as tb
    import src.cli.debug as debugcli

    report = json.loads((melee_root / "build" / "GALE01" / "report.json")
                        .read_text(encoding="utf-8"))
    fns = list(_iter_matched_functions(report))
    if limit:
        fns = fns[:limit]

    n_fpr = clean = excl = perfect = imperfect = characterized = 0
    misses: list = []
    agent_root = melee_root / "tools" / "melee-agent"
    with debugcli._acquire_checkdiff_repo_lock(melee_root, label="fpr sweep"):
        env = debugcli._checkdiff_env_for_locked_child(disable_fingerprint=False)
        for uname, fname in fns:
            # unit name in the report maps to src/<unit>.c (strip a trailing .o
            # / leading obj dir if the Step-3 probe showed one).
            unit_rel = uname.removesuffix(".o")
            tu = melee_root / "src" / f"{unit_rel}.c"
            if not tu.exists():
                continue
            out = tu.parent / f".{fname}.fprsweep.{os.getpid()}.pcdump.txt"
            proc = subprocess.run(
                [sys.executable, "-m", "src.cli", "debug", "dump", "local",
                 str(tu), "--function", fname, "--output", str(out),
                 "--no-cache-sync"],
                cwd=agent_root, capture_output=True, text=True, timeout=600,
                env=env)
            if proc.returncode != 0 or not out.exists():
                out.unlink(missing_ok=True)
                continue
            text = out.read_text(encoding="utf-8")
            out.unlink(missing_ok=True)
            ig = tb.load_ig(text, fname, class_id=1)
            if ig is None:
                continue                                  # not FPR-bearing
            n_fpr += 1
            if any(n.incomplete for n in ig.nodes.values()):
                excl += 1
                continue
            clean += 1
            g1 = tb.validate_g1(ig, fname)
            if g1.rate == 1.0:
                perfect += 1
            else:
                imperfect += 1
                label = next((lab for lab, pred in
                              (exclusion_predicates or {}).items() if pred(ig)),
                             None)
                if label:
                    characterized += 1
                misses.append({"function": fname, "unit": uname,
                               "g1_rate": g1.rate, "exclusion": label})

    tally = SweepTally(n_fpr=n_fpr, clean=clean, excluded_truncated=excl,
                       g1_perfect=perfect, g1_imperfect_clean=imperfect,
                       characterized_exclusions=characterized)
    verdict = classify_sweep(tally)
    verdict["misses"] = misses
    return verdict


def _write_doc(verdict: dict, out_path: Path) -> None:
    lines = ["# Surrogate-solver FPR G1 sweep (spec §5)", "",
             f"VERDICT: {verdict['verdict']}", ""]
    for k in ("n_fpr", "denominator_clean", "excluded_truncated", "g1_perfect",
              "g1_imperfect_clean", "characterized_exclusions",
              "uncharacterized", "uncharacterized_rate", "remedy",
              "fpr_coverage"):
        if k in verdict:
            lines.append(f"- {k}: {verdict[k]}")
    lines += ["", "## Misses", ""]
    for m in verdict.get("misses", []):
        lines.append(f"- {m['function']} ({m['unit']}): g1={m['g1_rate']:.3f} "
                     f"exclusion={m['exclusion']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--melee-root", type=Path,
                    default=Path(__file__).resolve().parents[4])
    args = ap.parse_args()
    v = run_fpr_sweep(melee_root=args.melee_root, limit=args.limit)
    _write_doc(v, args.melee_root / "docs" / "superpowers" / "results"
               / "2026-06-12-surrogate-solver-fpr-sweep.md")
    print(json.dumps({k: v[k] for k in v if k != "misses"}, indent=2))
```

- [ ] **Step 5: Run the classifier tests to verify they pass**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/test_fpr_sweep.py -q --no-cov`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the live sweep (sizing first via --limit, then full)**

```bash
cd <WT>/tools/melee-agent && python -m src.search.solver.fpr_sweep --limit 25 2>&1 | tail -15
```
Sanity-check the sizing on 25 functions, then run WITHOUT `--limit` (long; time-box per rev3's 3 working days). The doc is written on every run. **If `hard_stop`:** record it; the Task-18 FPR pilot is SKIPPED-and-recorded; characterize misses (add a documented `exclusion_predicates` entry ONLY with written justification) and re-run, or ship GPR-only.

- [ ] **Step 7: Commit**

```bash
cd <WT> && git add tools/melee-agent/src/search/solver/fpr_sweep.py tools/melee-agent/tests/search/solver/test_fpr_sweep.py docs/superpowers/results/2026-06-12-surrogate-solver-fpr-sweep.md && git commit -m "feat(solver): FPR G1 sweep — STRICT classifier (any uncharacterized miss = hard stop) + complete live driver (T17)"
```

---

### Task 18: Pilots (§6) — end-to-end on named functions + the §3 live gate

Run the live CLI end-to-end on the §6 pilots, re-verified against FRESH upstream first. The 8024714C BANK pilot is now meaningful: pair composition is real (Task 5) and the FPR sweep gates it (Task 17).

**Files:**
- Create: `docs/superpowers/results/2026-06-12-surrogate-solver-pilots.md`

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Re-verify the pilot functions against FRESH upstream**

```bash
cd <WT> && git fetch upstream 2>/dev/null; for fn in mnDiagram_80241E78 mnDiagram2_CreateStatRow mnDiagram3_8024714C mnDiagram_CursorProc; do printf '%-26s ' "$fn"; git grep -c "$fn" upstream/master -- 'src/melee/mn/*.c' 2>/dev/null | head -1 || echo 'absent'; done
```
Record results; substitute moved/matched functions with the nearest in-pool register-only partial and note it in the pilot log.

- [ ] **Step 2: Pilot 1 — mnDiagram_80241E78 (GPR, WIN-expected) + the live §3 gate**

```bash
cd <WT>/tools/melee-agent && python -m src.cli debug solve coloring -f mnDiagram_80241E78 --json 2>&1 | tail -60; echo "exit: $?"
```
Expected: exit 0; the top-8 contains the loop-tail data-alias node-add (admitted by §1.5). Then exercise the LIVE §3 gate: write the alias C move into the TU (per the worksheet's c_realization), rebuild + dump (`debug dump local`), and run `gate.re_extract_and_classify` with the pre-edit baseline IG → expect `surrogate-confirmed`. Restore the TU afterward (`git checkout -- src/melee/mn/mndiagram.c`) unless committing the match. Record the outcome in the proposal-confirmation tally.

- [ ] **Step 3: Pilots 2, 3, 8**

```bash
cd <WT>/tools/melee-agent && python -m src.cli debug solve coloring -f mnDiagram2_CreateStatRow 2>&1 | tail -12; echo "exit: $?"
cd <WT>/tools/melee-agent && python -m src.cli debug solve coloring -f mnDiagram3_8024714C --class fpr 2>&1 | tail -12; echo "exit: $?"
cd <WT>/tools/melee-agent && python -m src.cli debug solve coloring -f mnDiagram_CursorProc 2>&1 | tail -12; echo "exit: $?"
```
Expected: Pilot 2 → exit 4 `reason: window-order` (filter (c) negative control); Pilot 3 → exit 4 budgeted no-candidate after singles AND pairs (SKIP + record if Task 17 hard-stopped); Pilot 8 → exit 0 with the gp/flow-alias top-8, then the live §3 confirm against the post-alias variant (mirrors the calibration fixture but through the live CLI path). If a fresh `extract list` surfaces an in-pool allocator-cascade GPR partial (GetRanked*/GetLeastPlayed*) verified against upstream, run it as the optional real pair-escalation pilot (spec §10 Q6).

- [ ] **Step 4: Write the pilot log + commit**

Create `docs/superpowers/results/2026-06-12-surrogate-solver-pilots.md`: per-pilot exit code, expected-vs-actual, the LIVE §3 outcomes, the extended proposal-confirmation rate (calibration n=2 + live pilots), substitutions, and any divergence framed as MODEL GAP (never "MWCC quirk").

```bash
cd <WT> && git add docs/superpowers/results/2026-06-12-surrogate-solver-pilots.md && git commit -m "docs(solver): pilot log — §6 pilots + live §3 confirmations + proposal-confirmation rate (T18)"
```

---

### Task 19: Full-suite regression gate + self-review fixes

- [ ] **Step 0: Phase-1 preflight**

Run the Task 13 Step 0 command. Expected: `PHASE-1 PREFLIGHT: OK`.

- [ ] **Step 1: Run the entire solver suite (units + calibration gate + controls)**

Run: `cd <WT>/tools/melee-agent && python -m pytest tests/search/solver/ -q --no-cov 2>&1 | tail -5`
Expected: PASS, with the calibration module NOT skipping.

- [ ] **Step 2: Confirm CLI health + no legacy-sibling drift**

Run: `cd <WT> && git status --porcelain tools/melee-agent/src/cli/debug.py tools/melee-agent/src/search/cli.py && cd tools/melee-agent && python -c "import src.cli.debug as d; print('coloring' in [c.name for c in d.solve_app.registered_commands])"`
Expected: `git status` prints nothing; the import prints `True`.

- [ ] **Step 3: Commit any self-review fixes**

```bash
cd <WT> && git add -A && git commit -m "fix(solver): self-review regression fixes (T19)" || echo "no fixes needed"
```

---

## Deviations

Deliberate deviations from a literal reading of the spec, each with its reason. None changes a spec contract.

1. **Phase 0 builds the production core BEFORE the calibration gate.** Rev3 §1.5 requires the gate to run "the FULL solver (`solve_coloring`, §2)" on the five fixtures — impossible without the core. What rev3 actually gates is wiring enumeration "into a driver/permuter application loop"; this plan therefore gates Phase 1 (CLI, D0 default, suggest conversion, sweep, pilots) on the n≥5 result and keeps the core build (Tasks 1-9) mwcc-free and pre-gate. (Codex blocker 2 resolution; supersedes rev-1's spike-harness reading.)

2. **`pair_escalation.pair_hits` is a recorded schema EXTENSION.** Spec §7 lists `pair_escalation:{ran, reason, frontier_size, frontier}`; §4.1/§6-N7 require reporting whether an actionable PAIR was found ("no actionable single AND no actionable pair" decides exit-4; N7's PASS is "finds the pair"). The found pairs must live somewhere reportable; `pair_hits` (each `{perturbations:[2], targets_met, predicted_assignment_delta, actionable}`, plus `pair_evals`/`truncated` telemetry) is the minimal faithful addition. Mirrors the precedent plan's `named_pair` schema addition (its Deviation 9).

3. **Pure-core + thin-seam split throughout** (`classify_fidelity`/`re_extract_and_classify`, `classify_sweep`/`run_fpr_sweep`, `solve_coloring` with injected collaborators). Live mwcc orchestration cannot be unit-tested in CI; every seam is exercised at the calibration gate (frozen real artifacts) or the pilots (live). Unlike rev 1, NO seam carries hardcoded-permissive defaults: the probe signals always flow through `probe.py`'s production derivations (codex blocker 3).

4. **`copy_already_survives` is derived from a function-level window-shift classifier** (`is_window_order_residual`: uniform callee-save observed−desired delta). Rev3 §1.5(c) describes the CreateStatRow evidence in force-phys terms; the uniform-shift signature is the mechanically checkable form of "the copy already survives and the residual is only the window base." Stated as a heuristic; validated by the flag_c calibration fixture (a wrong classifier fails the gate).

5. **`use_set_family` and the L1 survival check use the IG neighbor set as the use-set proxy.** The surrogate cannot see per-instruction uses (spec §3 "liveness the surrogate can't see"); the partition-hypothesis family is explicitly an approximation in spec §1a, and the all-uses member is generated so the L1 reject is observable in `filter_summary`. §3 re-extraction remains the ground truth.

6. **The §3-style calibration confirmation uses the frozen POST-win artifacts** (alias-attributed node present in the post IG; the post commit is the recorded byte-improvement) rather than a live rebuild — the true rate over live builds is extended at the Task-18 pilots. The variant-specific `ig_idx` risk (spec §3) is why the check matches on source-attribution, not ig numbers.

7. **`surrogate_confidence` is computed by `worksheet.classify_confidence` from two booleans** (full target vector; tier-a realization with resolved source object), pinning the §7/rev2-6 definition in one place.

---

## Codex review disposition (rev 1 → rev 2)

| # | Severity | Finding | Disposition in rev 2 |
|---|---|---|---|
| 1 | BLOCKER | Pair composition missing; N7 asserted only "callback ran"; 8024714C BANK false-passable | **FIXED — T5 + T15.** `compose_frontier_pairs` is production (apply both → predict → pair hits, remaining-budget accounting, truncation), the DEFAULT `_pair_impl`; T5 tests find the working pair on a verified pair-only IG + respect the budget; T15 N7 asserts the recorded `working_pair` IS FOUND (kind+target_ig match) and brute-force-confirms no-single with the production enumerator; T9 exit-0 includes actionable pairs so exit-4 means "no single AND no pair". Deviation 4 (stub) WITHDRAWN. |
| 2 | BLOCKER | Phase 0 ran a spike harness on possibly-synthetic structured inputs with a proxy confirmation rate | **FIXED — Phase-0 restructure (T1-T12).** Production core built first; T10 freezes the five fixtures from REAL functions via a lock-safe live generator (loud abort, never a placeholder; fresh-upstream re-verify); T11 runs PRODUCTION `solve_coloring` through production `explain_virtuals`/probe/enumerate/assemble paths on the frozen artifacts; the TRUE §3-style confirmation runs against frozen post-win artifacts (proxy metric dropped); gate doc carries a machine-checkable `GATE:` line. |
| 3 | BLOCKER | T13 hardcoded permissive `ProbeContext` (S2/80242C0C/CreateStatRow would pass live) | **FIXED — T4 + T14.** New `probe.py` derives all four signals from production sources (first-def opcode li/lis → rejected_a; source None → rejected_b; window-shift residual → flagged_c; strict-subset use-set → rejected_survival), unit-tested per key; the CLI builds its `probe_ctx_fn` via the testable `_solver_probe_ctx_factory`, with a CLI-level test exercising all four reject/flag keys. No hardcoded signals remain. |
| 4 | MAJOR | Phase-0/1 gate textual only | **FIXED — T12 + T13 Step 0.** The verdict doc's first line is machine-checkable (`GATE: PASS`); every Phase-1 task starts with a fail-closed grep preflight; the Phase-1 header forbids parallel dispatch pre-gate. |
| 5 | MAJOR | D0 after CLI wiring | **FIXED — reorder.** D0 (T13) precedes the CLI (T14); the CLI's `--catalog-dir` default points at the already-existing tracked dir; the calibration gate reads the frozen snapshot (no memory-dir dependency in tests). |
| 6 | MAJOR | `--kinds edge` fell through to the order generator | **FIXED — T5 `normalize_kinds`.** `edge` expands to `edge-add`+`edge-remove`; unknown kinds raise; tested with the advertised default string; the CLI passes the advertised vocabulary through. |
| 7 | MAJOR | Empty-target abstain patched only in T14 (exit contract temporarily false) | **FIXED — T9.** The empty-`phys_target` abstain guard + test live in solve.py's own task before its commit; T15 N4 re-asserts it as a named negative-control regression. |
| 8 | MAJOR | FPR sweep live body a stub; classifier relaxed uncharacterized ≤5% misses | **FIXED — T17.** `run_fpr_sweep` fully implemented (report.json schema probe step + accessor lines, per-fn dump under the lock contract, class-1 tally, doc writer, `--limit` sizing); classifier STRICT: any uncharacterized clean miss → `hard_stop` (remedy `fix-fpr-dispense-reading` ≤5% / `ship-gpr-only` >5%); `proceed_filtered` only when EVERY miss has a documented static exclusion. |
| 9 | MAJOR | No-op inferred from prediction equality | **FIXED — T8.** `ig_structurally_equal` (select order + node set + neighbor sets vs the BASELINE IG) is the only no-op signal; `re_extract_and_classify` takes `baseline_ig`; a test pins that a perfectly-predicted real landing CONFIRMS. |
| 10 | MAJOR | `_assemble_realized` hand-waved, mocked out | **FIXED — T7.** `assemble_realized` is production code in realize.py with 9 direct tests: leads routing, window rows, FilterSummary/evals pass-through, `classify_confidence` use, tier/churn ranking, pair-hit enrichment + actionability. The CLI and the calibration gate both call it. |
| 11 | MINOR | Wrong `parents[]` indices (N7, catalog) | **FIXED — T15/T13.** N7 uses `parents[2]/"fixtures"`; the catalog test uses `parents[5]/"docs"` with a first test that prints the resolved path on failure. |

**Codex Deviation-4 ruling (REJECT the stubbed pair body): ACCEPTED** — the stub is withdrawn; full composition shipped in T5 (see finding 1).

---

## Self-review (writing-plans discipline)

### Spec-coverage map (every spec section → implementing task)

| Spec section | Implementing task(s) |
|---|---|
| §1a node-add primitive | T2 (`perturbations.add_node`) |
| §1b edge-add/remove | T2 (`add_edge`/`remove_edge`) |
| §1c REF-count bump (annotation via node-add, not a standalone kind) | T1/T2 (no separate kind — verified) |
| §1d coalesce-veto behind `--experimental-kinds` | T1 (`COALESCE`), T2 (`apply` raises), T14 (flag) |
| §1e order kept, ranked last | T2 (`move_order`), T7 (tier c), T13 catalog (`order.json` tier c + census note) |
| §1.5 L1 + L2 (a)/(b)/(c) filter | T3 (predicate), T4 (production signal derivations) |
| §1.5 (c) flag-and-quarantine still-enumerated + exit-4 window-order | T5 (window bucket evaluated), T9 (exit-4 reason), T11 (flag_c fixture) |
| §1.5/§9 FIVE permanent fixtures, FULL solver, n≥5 gate, confirmation rate, 1-hop check | T10 (real freeze), T11 (production gate + §3 confirmation + 1-hop test), T12 (checkpoint) |
| §2 solve loop | T9 (`solve_coloring`), T11/T14 (frozen/live collaborator wiring) |
| §2 step 4 ranking (tier a/b/c, size, churn; tooling_leads) | T7 (`assemble_realized` + `lever_priority_rank`) |
| §2 step 5 pair escalation on no-actionable-single; F tunable | T5 (`enumerate_with_escalation` + `compose_frontier_pairs`), T15 (N7 + finding-3 regression) |
| §2.1 bounded generators + 200k cap + reserved floors + truncation + evals_per_kind | T5 (`EnumConfig`, budgets, tallies) |
| §3 fidelity gate (confirmed/fidelity-miss/realization-miss; UNATTRIBUTED no-op) | T8; T11 (frozen confirmation); T18 (live) |
| §4/§4.1 RUN/ABSTAIN/BANK; budgeted-no-candidate language | T9 (exit contract incl. K/F/cap reason string) |
| §5 FPR staged sweep (sizing, clean fixtures, fallback, HARD STOP) | T17; T18 Pilot 3 gated on it |
| §6 pilots 1/2/3/8 + optional pair pilot | T18 |
| §6 negative controls N4-N7 | T15 (N4/N5/N6/N7 incl. pair-FOUND) |
| §7 D0 sequencing (post-calibration, pre-driver-wiring) | T13 before T14 (verified order) |
| §7 CLI shape + exit codes | T14 (signature verbatim), T9 (codes) |
| §7 worksheet schema + surrogate_confidence definition | T6 (verbatim keys + `classify_confidence`); `pair_hits` extension recorded (Deviation 2) |
| §7 file layout + `solve_app` group | T0-T9, T14 |
| §7 reuse of directed patterns | T8 (UNATTRIBUTED discipline), T10 (generate.py pattern), T14 (`_collect_order_target_inputs`) |
| §7 `suggest register-tiebreak` thin caller | T16 |
| §8 non-goals | order ranked last (T7/T13); coalesce flagged (T2); no auto-synthesis (worksheet only, T6/T14); no IG-construction model (node-add = IG edit + §3 re-extract, T2/T8); no DLL changes (none touched) |
| §9 test strategy items | T11 (spike-as-gate), T17 (sweep), T3 (filter units incl. admit case), T2 (primitive units incl. remove(88,37)), T8 (gate classification), T9/T15 (exit codes + controls), T15 (pair-gating regression) |
| §10 open Q1 (1-hop) | T11 1-hop test + T5 `implicated_hops` widen knob |
| §10 open Q2 (use-set family) | T5 fixed-4 family (Deviation 5) |
| §10 open Q3 (sequential K=1; no outer loop in v1) | T9 `max_perturb=2`; no apply→re-solve loop built (driver re-runs manually) |
| §10 open Q4 (frontier F) | T5 `EnumConfig.frontier=32`, T14 `--frontier` |
| §10 open Q5 (tooling_leads signal) | T7 routing + T6 field; visible in CLI summary (T14) |

**Coverage: every spec section maps to ≥1 task; the codex spec-coverage table's MISSING/PARTIAL rows are all upgraded** (pair composition T5; Phase-0 production gate T10-T12; probe derivations T4/T14; D0 order T13; kind normalization T5; N4 in T9; FPR T17; no-op T8; assemble T7; paths T13/T15).

### Placeholder scan

No `TODO`, no "similar to Task N", no NotImplementedError anywhere (the rev-1 `run_fpr_sweep` stub is replaced by a complete implementation; the rev-1 `__import__`/dead-line snippet warts are removed). One explicitly-scoped optional note remains by design: the T14 `kinds=` passthrough for a NON-default `--kinds` (an exactly-specified 3-line change with its own test when exercised; the default path is fully implemented). The T17 `_iter_matched_functions` accessor lines are pinned to the Step-3 schema probe output (a deterministic verify-then-fill, not a placeholder).

### Type-consistency check (cross-task field/name drift)

- **`PerturbationKind` values** (T1) ←→ `apply` dispatch (T2) ←→ filter bypass (T3) ←→ generator kinds + `normalize_kinds` (T5) ←→ catalog keys (T7/T10/T13). Consistent; `edge` exists only in the ADVERTISED vocabulary and is normalized before generation.
- **Filter reasons** `rejected_a/rejected_b/flagged_c/rejected_survival` (T3) == `filter_counts` keys (T5) == `FilterSummary` fields (T6) == calibration assertions (T11). Consistent.
- **`ProbeContext` fields** (T3) == `derive_probe_context` output (T4) == `_solver_probe_ctx_factory` (T14) == calibration wiring (T11). Consistent.
- **`EnumResult` fields** (`full_hits/partial_hits/window_order_hits/filter_counts/evals_per_kind/truncated/last_kind`) (T5) == `assemble_realized` consumption (T7) == escalation stubs in tests (T5/T15). Consistent.
- **`RealizedBundle` fields** (T7) == `solve_coloring` consumption (T9) == solve-test stubs (T9). Consistent.
- **Worksheet keys** (T6, asserted exact) == spec §7 + the recorded `pair_hits` extension == CLI `to_json` output (T14). Consistent.
- **`surrogate_confidence`** `high|proposal` (T6) vs `confidence_tier` `a|b|c` (T7) — distinct, never conflated (T6/T7/T14 tests assert each).
- **Exit codes 0/3/4** (T9) == CLI `typer.Exit(res.exit_code)` (T14) == N4/N5 controls (T15) == pilots (T18). Consistent.
- **Pair-hit shape** `{perturbations, targets_met, delta→predicted_assignment_delta, actionable}` — raw in T5 (Perturbation objects), serialized in T7 (`serialize_perturbation`), asserted in T9/T15. Consistent (T7 is the single serialization point).
- **Fixture paths** — calibration `parents[2]/fixtures/solver/calibration` from `tests/search/solver/` (T11), N7 `parents[2]/fixtures/solver/n7_pair` (T15), catalog `parents[5]/docs/superpowers/lever-catalog` (T13). Verified against the directory layout.

No drift found. Any drift surfaced during execution is fixed in T19 Step 3.

---

## Notes for the executor

- **The Task-12 checkpoint is a hard gate**, and Phase 1's Step-0 preflights enforce it mechanically. Do NOT dispatch Phase-1 tasks (even in parallel) before `GATE: PASS`.
- **The surrogate (`tiebreak.py`) is never modified.** If a task seems to require editing `predict_assignments`/`load_ig`, STOP and report.
- **Lock contract applies only to the live tasks** (T10 generator, T17 sweep, T18 pilots, optional T15 primary derivation). Everything else is mwcc-free.
- **Honesty over green.** A calibration miss (T11), a fixture that cannot be frozen from real artifacts (T10), an FPR `hard_stop` (T17), or a pilot diverging from §6 (T18) are VALID outcomes to report — record them (MODEL GAP framing, never "MWCC quirk") rather than forcing a pass.

