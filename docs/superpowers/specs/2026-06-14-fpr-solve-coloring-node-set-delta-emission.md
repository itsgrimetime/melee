# Spec: `solve coloring --class fpr` emits a node-set-delta worksheet (issue #705)

## Status

Design for the **remaining** half of issue #705. The FPR node-set-split
*vocabulary* (candidate generation) already shipped (commits `ede43f8db`,
`f1ef0005a`, `0a195340b`, `a0d59f2c7`; plan `2026-06-14-fpr-node-set-split.md`).
This spec closes the gap that left the plan's Step-4 live smoke failing:
`debug solve coloring -f <fn> --class fpr --json` still emits **no**
`node_set_delta`, so the "ranked worksheet with per-virtual split recipes"
deliverable is unmet and the vocabulary is unreachable from the solver.

## Problem

`solve coloring --class fpr` abstains with exit 3 and an empty payload on FPR
coloring residuals (e.g. `mnDiagram_80241E78`). Two coupled causes, both rooted
in the #619 register-only admission gate:

1. **Empty `phys_target`.** `_collect_order_target_inputs` runs the
   `is_register_only_admission` gate; when `admitted=False` it short-circuits to
   `_inert()` (empty `phys_target`) *before* deriving any per-class target. FPR
   residuals fail the gate because their normalized diff carries non-register
   lines (see facts below), so no target is ever derived.
2. **Dropped `node_set_delta` on the step-1 abstain.** `_derive_node_set_delta_payload`
   already exists and is already wired into `_run_solve_coloring` (FPR-aware,
   `f`-prefix), and `solve_coloring` already threads `node_set_delta` on the
   **force-phys-collision** abstain (`solve.py:68-72`, tested). The gap is
   narrow: the **step-1 `if not pre.register_only` abstain** (`solve.py:61`)
   does **not** thread `pre.node_set_delta`. FPR residuals abstain there (they
   are genuinely not register-only), so the worksheet payload is lost.

Net: the producer (`solve coloring`) never feeds the already-built consumer
(`solve node-set-split`) for FPR residuals, because it abstains at the gate
(cause 1) and the one abstain it would otherwise hit drops the delta (cause 2).

## Facts established by investigation (HEAD `b6ed34a86`, `mnDiagram_80241E78`)

- checkdiff classification `primary = instruction-sequence`; 22 normalized diff
  lines; `register-allocation guidance: callee-save swap r25<->r26`.
- `is_register_only_admission` returns `admitted=False`: `check_i_bl_multiset_equal=True`
  (no call added/removed/re-pointed) but `check_ii_all_normalized_lines_register_class=False`
  (22 non-register lines from a float-constant data-pool materialization
  `lis/addi + R_PPC_ADDR16_HA/LO -> lfd` scheduled differently around an `fsubs`).
- The residual is **coupled**: a GPR `r25<->r26` callee-save swap (class 0,
  igs 34/47/58) + the instruction-sequence float scheduling + FPR register
  reassignments (class 1: ig37 `f28->f26`, ig33 `f27->f28`, ig38 `f30->f0`,
  ig56 conflict). The `fmuls` differ in **operands** too (`fmuls f26,f26,f0`
  vs `fmuls f28,f1,f0`) — a genuine reassociation/scheduling difference.
- Forcing the FPR target (`--force-phys 1:39:26,1:33:28`) does **not** match:
  the GPR swap and instruction-sequence divergence persist. The issue's
  "Force-phys proves reachability" premise is stale; **Arm 1 (crack 80241E78 via
  an FPR split) is implausible** — it is not a clean FPR-coloring problem.
- `_derive_force_phys_from_register_diff_lines` filtered to class 1 **does**
  produce a coherent FPR target + conflict for 80241E78. So the feature *can*
  emit a node_set_delta; the gate is the only blocker.

## Insight

The register-only admission is the **wrong gate** for the node-set-split use
case. Node-set-split exists precisely for residuals that are *not* reachable by
reordering (the `structurally-different-virtual` blocker). Requiring the
residual to be register-only contradicts the feature's purpose.

The **sound** admission for emitting an FPR node-set-delta is:
(a) **call-shape parity** (`bl`-target multiset equal — same algorithm), and
(b) a **non-empty class-1 register-diff target** (a real FPR coloring residual
exists). Both are already computed today (the gate's `direct_evidence` carries
`check_i_bl_multiset_equal`; the vector carries class-1 targets).

## Design (minimal, additive, FPR-scoped)

1. **`_collect_order_target_inputs(..., node_set_delta_fallback: bool = False)`.**
   Initialize `gate_verdict = None` in the `else` (label-gate) branch so it is
   in scope on all paths. Compute
   `node_set_fallback = (node_set_delta_fallback and not admitted and
   register_only_gate is not None and
   gate_verdict["direct_evidence"]["check_i_bl_multiset_equal"])`. Change the
   short-circuit `if not admitted: return _inert()` to
   `if not admitted and not node_set_fallback: return _inert()` so the fallback
   proceeds through the existing baseline-pcdump + vector derivation. The
   derivation requires the baseline pcdump (for `pre_pass`), so the fallback
   pays **two builds** (the gate's checkdiff + the baseline dump); it then
   returns **early**, skipping the anchor search + force-vector probe (the
   costly #639 cascade trap, irrelevant here). Two sub-cases after the vector
   is derived:
   - **Conflicts present:** the *existing* `if phys_conflicts: return
     _inert(phys_target=..., phys_conflicts=...)` (today before the probe)
     already returns correctly — for the fallback, also attach `coupled_residual`.
   - **Targets, no conflicts:** add a new
     `if node_set_fallback: return _inert(phys_target=phys_target,
     coupled_residual=...)` immediately after the conflict return, before the
     anchor search.
   If both `phys_target` and `phys_conflicts` are empty on the fallback, fall
   back to `_inert()` (nothing to split). `register_only` /
   `direct_evidence_register_only` stays `False` (genuinely not register-only).

2. **`solve_coloring` (solve.py) step-1 abstain threads the delta:**
   `return _abstain("checkdiff not register-only ...", node_set_delta=pre.node_set_delta)`.
   One-line change. No-op for GPR and for register-only FPR (their `phys_target`
   on this path stays empty ⇒ `_derive_node_set_delta_payload` returns `None`).

3. **`_run_solve_coloring` wiring:** pass
   `node_set_delta_fallback=(class_id == 1)` to `_collect_order_target_inputs`.
   FPR-scoped; the GPR order-target path is untouched.

4. **Honest coupling annotation (must be COMPLETE).** On the fallback,
   `_collect_order_target_inputs` computes a `coupled_residual` summary carried
   on `DeriveInputs` and recorded by `_derive_node_set_delta_payload` on the
   emitted delta. It must cover **two** kinds of coupling, because a pure
   reassociation difference normalizes away and would otherwise leave an
   empty/clean-looking annotation (review Finding 1):
   - **Cross-class / surviving-structural:** count of other-class register-diff
     targets (e.g. the GPR `r25<->r26` swap) + the gate's
     `nonregister_class_lines`.
   - **Reassociation-suspected class-1 targets:** count of class-1 target
     occurrences whose *defining* instruction is a multi-source FP arithmetic op
     (`fmuls`/`fadds`/`fsubs`/`fmadds`/`fdivs`/…) whose **source** operands differ
     between target and current asm (not just the destination register). For
     80241E78, `fmuls f26,f26,f0` vs `fmuls f28,f1,f0` is such a case. A reader
     then knows the lever is operand-commute/reassociation, not a pure split,
     and that the worksheet may be a no-op for a coupled residual.

   This prevents the worksheet from reading as a false "splittable" lead. We
   **annotate, never suppress** — the triage value of converting "abstain, exit
   3, empty" into "here is the FPR residual and why a split alone won't close it"
   is the point of the feature.

## Out of scope

- Cracking `mnDiagram_80241E78` (Arm 1). The residual is coupled; the FPR split
  family cannot fix the GPR swap or the data-pool scheduling. We do not claim it
  is unmatchable (the C provably exists) — only that *this* per-class tool is
  not the lever, which the `coupled_residual` annotation states honestly.
- GPR (class 0) node-set-delta emission on the not-register-only path
  (`#618`/`#622`; those are blocked on a separate force-dispense-order DLL hook).
  The `node_set_delta_fallback` parameter is generic, but only the FPR CLI wires
  it on, so GPR behavior is byte-identical.

## Validation / stop condition (issue #705)

- **Feature smoke** (the plan's failing Step 4): `solve coloring -f
  mnDiagram_80241E78 --class fpr --json` now emits `node_set_delta`
  (`class_id=1`, `register_prefix="f"`, non-empty `missing_virtuals`,
  `coupled_residual` present); `solve node-set-split --node-set-delta <file>`
  consumes it with `generated_count > 0`.
- **Triage ≥10 FPR functions.** Run the full pipeline on 80241E78 plus the other
  near-100 FPR-residual functions (`mnDiagram3_8024714C`, `mnDiagram3_80245BA4`,
  and ≥7 more discovered via report.json / `fpr_sweep`). Record per-function
  improvement. If one improves ≥0.1% ⇒ **Arm 1**; else 10 functions triaged with
  0 improvements ⇒ **Arm 2**. Either arm resolves #705.

## Soundness / regression guards

- `bl`-multiset parity REQUIRED on the fallback (calls differ ⇒ `_inert()`,
  no delta). Guard also requires `register_only_gate is not None` (the label-gate
  path has no `direct_evidence`; `gate_verdict` is `None` there).
- Non-empty class-1 target REQUIRED (no FPR residual ⇒ delta `None`).
- `node_set_delta_fallback` defaults `False`; order-target-derivation callers
  (`order-target derive` CLI at `__init__.py:14954`, calibration/order-distance
  fixtures) are byte-identical. The only production caller that turns it on is
  `_run_solve_coloring` for `class_id == 1`.
- FPR-scoped at the CLI; GPR `solve coloring` output unchanged (the fallback
  branch is dead for `node_set_delta_fallback=False`).
- Force-vector probe still runs for the admitted (register-only) path; only the
  not-admitted FPR fallback skips it.
- **Consumer is the real safety net (review Finding 1 mitigation):**
  `solve node-set-split` only scores candidates that actually move the target ig
  to the desired register and only *accepts* candidates that improve real
  checkdiff by `--threshold` (default 0.05). A spurious/no-op FPR worksheet
  therefore cannot cause a bad commit through the documented pipeline — it costs
  compile budget and (without the complete `coupled_residual` annotation) could
  mislead a human reader. The annotation closes the human-reader gap.

## Test plan (TDD)

- Unit (`test_cli_solve.py`): `_collect_order_target_inputs` fallback returns a
  populated `phys_target` + `coupled_residual` when `admitted=False`,
  `node_set_delta_fallback=True`, bl-parity True, class-1 targets present
  (monkeypatch the build/checkdiff/dump subprocess seams the existing solve
  tests already stub).
- Unit: fallback returns `_inert()` (no delta) when bl-parity False, when no
  class-1 target, and — **review Finding 2** — when `register_only_gate is None`
  (no `NameError`).
- Unit (regression): GPR not-admitted + `node_set_delta_fallback=False` still
  `_inert()`; and `_run_solve_coloring` for `class_id == 0` passes
  `node_set_delta_fallback=False` (pin the FPR scoping).
- Unit (solve.py): step-1 not-register-only abstain carries `node_set_delta`
  when present; still `None` when absent. Existing force-phys-collision
  threading tests stay green.
- Unit (`_derive_node_set_delta_payload`): emits `coupled_residual` when passed,
  including a **reassociation-suspected** fixture (the only class-1 diff is a
  multi-source FP op with differing source operands) so `coupled_residual` is
  populated, not empty (**review Finding 1**).
- CLI/live smoke: the Step-4 commands above.
