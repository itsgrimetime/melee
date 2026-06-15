# Plan: `solve coloring --class fpr` node-set-delta emission (issue #705)

> Implements `docs/superpowers/specs/2026-06-14-fpr-solve-coloring-node-set-delta-emission.md`.
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development (TDD per task).
>
> **WORKSPACE CONTRACT (critical):** All work happens in the worktree
> `/Users/mike/code/melee-2` (branch `master-2`, == current master). Subagents:
> use ABSOLUTE paths under `/Users/mike/code/melee-2`; run every command after
> `cd /Users/mike/code/melee-2`; run the CLI as
> `PYTHONPATH=tools/melee-agent python -m src.cli ...`; run pytest as
> `PYTHONPATH=tools/melee-agent python -m pytest ...`. **NEVER** read, write, or
> build under `/Users/mike/code/melee` — it is a separate checkout with another
> agent's uncommitted work. Relative paths in subagents default to that wrong
> checkout; always anchor to `/Users/mike/code/melee-2`.

## Files

- `tools/melee-agent/src/mwcc_debug/order_target_derive.py` — `DeriveInputs`
  dataclass: add `coupled_residual` field.
- `tools/melee-agent/src/cli/debug/__init__.py` —
  `_collect_order_target_inputs` (fallback), `_run_solve_coloring` (wiring),
  `_derive_node_set_delta_payload` (annotation), and a new small helper
  `_fpr_reassociation_suspect_count`.
- `tools/melee-agent/src/search/solver/solve.py` — step-1 abstain threads delta.
- `tools/melee-agent/tests/search/solver/test_cli_solve.py` — unit tests.
- `tools/melee-agent/tests/test_node_set_split.py` — `_derive_node_set_delta_payload`
  `coupled_residual` test (if a closer home exists there; else test_cli_solve).

---

## Task 1 — `coupled_residual` field + reassociation-suspect helper (TDD)

**Files:** `order_target_derive.py`, `cli/debug/__init__.py`, `test_cli_solve.py`.

- [ ] **Step 1 (failing tests):** In `test_cli_solve.py`, add
  `test_fpr_reassociation_suspect_count`:
  - **flags** a class-1 target whose `fmuls` occurrence is `target_asm` ending
    `fmuls f26,f26,f0` vs `current_asm` ending `fmuls f28,f1,f0` → count 1 (the
    operand aliasing pattern flips: dest-aliases-src1 on target, not on current).
  - **pure-relabel CONTROL must yield 0** (review Finding 2): `fadds f28,f28,f30`
    vs `fadds f26,f26,f30` — a clean coloring relabel, identical structure →
    count 0. A raw-string source compare would WRONGLY count this 1; the test
    forces the relabel-invariant implementation.
  - **load control:** `lfs f0,60(r24)` / `lfs f30,60(r24)` (not a multi-source
    FP op) → count 0.
- [ ] **Step 2 (implement):**
  - In `order_target_derive.py` `DeriveInputs`, add as a defaulted field after
    `direct_evidence_register_only`:
    `coupled_residual: dict | None = None  # #705: honest coupling summary on the FPR node-set fallback`.
  - In `cli/debug/__init__.py`, add a module-level helper
    `_operand_shape(operands: str) -> tuple[int, ...]`: tokenize on `","`, strip
    each, and map tokens to first-occurrence indices (a relabel-INVARIANT
    canonical shape). E.g. `"f26,f26,f0"` → `(0,0,1)`; `"f28,f1,f0"` → `(0,1,2)`;
    `"f28,f28,f30"` and `"f26,f26,f30"` both → `(0,0,1)`.
  - Add `_fpr_reassociation_suspect_count(class_targets: list[dict]) -> int`:
    multi-source FP opcodes =
    `{"fadd","fadds","fsub","fsubs","fmul","fmuls","fdiv","fdivs","fmadd","fmadds","fmsub","fmsubs","fnmadd","fnmadds","fnmsub","fnmsubs","fsel"}`.
    For each target in `class_targets`, for each `occ` in
    `target.get("occurrences", [])`: `opcode = occ.get("opcode")`; if opcode in
    the set, compute the target shape from `occ.get("operands", "")` and the
    current shape from `_parse_checkdiff_asm_instruction(occ.get("current_asm") or "")`
    (`.operands` if the parse is not `None`, else `""`). Count the occurrence
    when the two shapes **differ** — i.e. the intra-instruction register-aliasing
    structure changed beyond a pure relabel (a reassociation/scheduling signal,
    NOT a coloring relabel). Be defensive: missing keys / `None` parse / empty
    operands contribute 0, never raise.
  - NOTE the metric name `reassociation_suspect_targets` is a heuristic
    label; document in the helper docstring that it detects relabel-invariant
    operand-structure differences and is a soft coupling hint (the consumer's
    verify-and-accept gate remains the real correctness check).
- [ ] **Step 3 (verify):**
  `cd /Users/mike/code/melee-2 && PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py -k reassociation_suspect -q`
  → passes. `python -m compileall -q tools/melee-agent/src` exits 0.

## Task 2 — `node_set_delta_fallback` in `_collect_order_target_inputs` (TDD)

**Files:** `cli/debug/__init__.py`, `test_cli_solve.py`. Depends on Task 1.

- [ ] **Step 1 (failing tests):** Add tests that monkeypatch the same subprocess
  seams the existing `_collect_order_target_inputs` tests use — model on
  `test_collect_order_target_inputs_empty_force_vector_window_abstains`
  (`test_cli_solve.py:1438`): stub `debugcli.subprocess.run` (returns checkdiff
  JSON + writes the dump `--output`), `_checkdiff_script_path`, `parse_pcdump`,
  `parse_hook_events`, `find_function`, `_derive_force_phys_from_register_diff_lines`,
  `asm_extract_function`, `asm_parse_prologue_end`, `asm_find_first_def`. For the
  FALLBACK cases the `register_only_gate` stub MUST return the full shape (NOT
  the `{"admitted": True}` one-liner that test uses):
  `lambda *a: {"admitted": False, "direct_evidence": {"check_i_bl_multiset_equal": True, "nonregister_class_lines": 22}}`.
  To prove the probe is skipped, stub `_run_force_vector_auto_verify` to raise
  and assert it is never reached. Cases:
  - `admitted=False`, `node_set_delta_fallback=True`, gate `direct_evidence`
    `check_i_bl_multiset_equal=True`, derived class-1 target present, no
    conflicts → returns DeriveInputs with non-empty `phys_target`, non-None
    `coupled_residual`, `forced_class_clean is False`, and does NOT call the
    force-vector probe (assert the probe seam is never invoked).
  - same but conflicts present → returns with `phys_target` + `phys_conflicts`
    + `coupled_residual` (the existing conflict-return path, now annotated).
  - `bl`-parity False → `_inert()` (empty `phys_target`, `coupled_residual` None).
  - no class-1 target derived → `_inert()`.
  - `register_only_gate is None` + `node_set_delta_fallback=True` → `_inert()`,
    NO `NameError` (review Finding 2).
  - GPR-style: `admitted=False`, `node_set_delta_fallback=False` → `_inert()`
    (unchanged).
- [ ] **Step 2 (implement):** Add `node_set_delta_fallback: bool = False` param.
  - In the gate `else` branch, also set `gate_verdict = None` so it is bound on
    all paths.
  - After `admitted` is computed, compute:
    ```python
    node_set_fallback = (
        node_set_delta_fallback and not admitted
        and gate_verdict is not None
        and bool(gate_verdict.get("direct_evidence", {})
                 .get("check_i_bl_multiset_equal"))
    )
    ```
  - Change `if not admitted:` → `if not admitted and not node_set_fallback:`
    (keep the existing comment + `return _inert()`).
  - Compute `coupled_residual` once the vector is derived (after `class_targets`
    / `phys_target` / `phys_conflicts` exist), only when `node_set_fallback`:
    ```python
    coupled_residual = None
    if node_set_fallback:
        other_class_targets = [t for t in vector["targets"]
                               if int(t.get("class_id", -1)) != class_id]
        de = gate_verdict.get("direct_evidence", {})
        coupled_residual = {
            "other_class_register_targets": len(other_class_targets),
            "other_class_target_regs": sorted({
                t.get("target_reg_name") for t in other_class_targets
                if t.get("target_reg_name")}),
            "nonregister_class_lines": int(de.get("nonregister_class_lines", 0)),
            "reassociation_suspect_targets":
                _fpr_reassociation_suspect_count(class_targets),
        }
    ```
  - At the existing `if phys_conflicts:` return, add `coupled_residual=coupled_residual`.
  - Immediately AFTER that conflict-return, add the no-conflict fallback return:
    ```python
    if node_set_fallback:
        if not phys_target:
            return _inert(coupled_residual=coupled_residual)
        return _inert(phys_target=phys_target, coupled_residual=coupled_residual)
    ```
    (This precedes the anchor search + force-vector probe, skipping them.)
  - Add `coupled_residual` to the `_inert` base dict default (`None`) so all
    returns carry the field; the `**over` already lets callers set it.
- [ ] **Step 3 (verify):** run the Task-2 tests + Task-1 tests; `compileall` 0.

## Task 3 — solve.py step-1 abstain threads `node_set_delta` (TDD)

**Files:** `solve.py`, `tests/search/solver/test_solve.py` (confirmed present; the
right home — it unit-tests `solve_coloring` directly with stub
`preconditions_fn`s). Model on the adjacent `test_abstain_exit3_on_force_phys_collision`
(`test_solve.py:50-62`), which already proves the force-phys-collision path
threads `node_set_delta`.

- [ ] **Step 1 (failing test):** extend `test_abstain_exit3_when_not_register_only`
  (`test_solve.py:84`) — or add a sibling `test_abstain_not_register_only_threads_node_set_delta`
  — with a stub `preconditions_fn` returning `register_only=False`, a populated
  `phys_target`, and `node_set_delta={"kind": "node-set-delta", ...}` → result
  `exit_code == 3`, `reason` starts "checkdiff not register-only",
  `result.node_set_delta == <that delta>`. Control (keep the existing assertion):
  `node_set_delta=None` → `result.node_set_delta is None`.
- [ ] **Step 2 (implement):** change the step-1 abstain (`solve.py:61-64`) to
  `return _abstain("checkdiff not register-only (admit set: ...)", node_set_delta=pre.node_set_delta)`
  (keep the exact reason text; just add the kwarg).
- [ ] **Step 3 (verify):** run the new test + the existing
  `test_solve_coloring_abstain_prints_node_set_delta` family → all green.

## Task 4 — wire fallback in `_run_solve_coloring` + record `coupled_residual` (TDD)

**Files:** `cli/debug/__init__.py`, `test_cli_solve.py`. Depends on Tasks 1-3.

- [ ] **Step 1 (failing tests):**
  - `_derive_node_set_delta_payload` records `coupled_residual` when passed a
    non-None value (add the new kwarg) and omits/None when not.
  - `_run_solve_coloring` passes `node_set_delta_fallback=True` for `class_id == 1`
    and `False` for `class_id == 0` (monkeypatch `_collect_order_target_inputs`,
    assert the kwarg value; review Finding 6).
- [ ] **Step 2 (implement):**
  - Add `coupled_residual: dict | None = None` param to
    `_derive_node_set_delta_payload`; when not None, set
    `payload["coupled_residual"] = coupled_residual` on the returned delta dict.
  - In `_run_solve_coloring`: pass `node_set_delta_fallback=(class_id == 1)` to
    `_collect_order_target_inputs`; pass
    `coupled_residual=getattr(inputs, "coupled_residual", None)` to the
    `_derive_node_set_delta_payload` call.
- [ ] **Step 3 (verify):** run all Task 1-4 tests; then the broad solver suite
  `PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/search/solver/ tools/melee-agent/tests/test_node_set_split.py -q` → green; `compileall` 0;
  `git diff --check` clean.

## Task 5 — live feature smoke (the spec's Step 4) + commit core

- [ ] **Step 1:** ensure the pcdump cache exists:
  `cd /Users/mike/code/melee-2 && PYTHONPATH=tools/melee-agent python -m src.cli debug dump local src/melee/mn/mndiagram.c --function mnDiagram_80241E78`
  (already generated in this session; re-run if missing).
- [ ] **Step 2:** run:
  ```bash
  PYTHONPATH=tools/melee-agent python -m src.cli debug solve coloring \
    -f mnDiagram_80241E78 --class fpr --json > /tmp/solve705.json
  PYTHONPATH=tools/melee-agent python - <<'PY' /tmp/solve705.json
  import json,sys; p=json.load(open(sys.argv[1]))
  d=p.get("node_set_delta"); assert d, p
  assert d["class_id"]==1 and d["register_prefix"]=="f", d
  assert d["missing_virtuals"], d
  print("coupled_residual:", d.get("coupled_residual"))
  print("FPR node_set_delta OK:", [m["target_ig"] for m in d["missing_virtuals"]])
  PY
  PYTHONPATH=tools/melee-agent python -m src.cli debug solve node-set-split \
    --node-set-delta /tmp/solve705.json --max-candidates 10 --budget 240 \
    --timeout 120 --json > /tmp/split705.json; echo "split rc=$?"
  ```
  Expected: the delta assertions pass; `coupled_residual` is populated
  (non-zero `nonregister_class_lines` and/or `reassociation_suspect_targets` for
  80241E78); `solve node-set-split` runs and reports a non-zero generated count.
  **First inspect `/tmp/split705.json` to confirm the exact summary key**
  (`generated_count` vs a nested `summary.*`) before hard-asserting it — avoid a
  flaky smoke from a key-name mismatch. Record status (0 = improvement, 4 =
  bounded negative evidence) and the stop reason.
- [ ] **Step 3:** commit the core feature + spec + plan (one commit). Verify the
  worktree has ONLY intended files staged.

## Task 6 — Triage ≥10 FPR functions (stop-condition validation)

> **Validity guard (review Finding 5):** "0 improvements" must be a real result,
> not a harness artifact. Two stratifications are mandatory:
> (1) record per-function `coupled_residual` and separate **clean** FPR residuals
> (low/zero `nonregister_class_lines`, zero `other_class_register_targets`, zero
> `reassociation_suspect_targets`) from **coupled** ones — only a clean residual
> that the split family fails to fix is strong Arm-2 evidence;
> (2) record the `solve node-set-split` **stop reason** (budget-exhausted /
> candidate-set-exhausted / all-candidates-wrong-register / improved-below-threshold)
> — a budget/cap exhaust is NOT "unsplittable." Confirm the exact summary keys
> for status + stop reason + `generated_count` by inspecting one real run's JSON
> before tabulating.

- [ ] **Step 1:** enumerate FPR-residual candidates: from
  `build/GALE01/report.json`, near-100% functions with a class-1 COLORGRAPH and
  an FPR register diff. Seed: `mnDiagram_80241E78`, `mnDiagram3_8024714C`,
  `mnDiagram3_80245BA4`; discover ≥7 more via
  `PYTHONPATH=tools/melee-agent python -m src.search.solver.fpr_sweep --limit N`
  and/or checkdiff scans for differing `f<N>` registers. Record each with
  baseline match%.
- [ ] **Step 2 (SERIALIZE):** for each function run `solve coloring --class fpr
  --json`; if a `node_set_delta` is emitted, feed it to `solve node-set-split`
  (bounded budget) and record: emitted-delta?, `coupled_residual` (all three
  counts), `generated_count`, status, **stop reason**, best Δmatch%, whether any
  candidate reached the target register. If `solve coloring` emits no delta
  (bl-parity fails / no FPR residual), record that verdict. **Run serially** —
  `_collect_order_target_inputs` wraps everything in the checkdiff repo lock, so
  parallel subagents on the same worktree serialize on the lock anyway; spawning
  off-master worktrees would give a stale baseline (see MEMORY
  `isolation_worktree_branches_off_master`). Keep everything pinned to
  `/Users/mike/code/melee-2`. (May dispatch ONE triage subagent that loops the
  list serially, or drive directly.)
- [ ] **Step 3:** tally into a table (function | baseline% | emitted-delta |
  coupled-counts | clean/coupled | generated | reached-target | stop-reason |
  Δ%). Decision:
  - If any function improves ≥0.1% with a verified, **shippable** source
    candidate → **Arm 1** (apply, rebuild, `checkdiff --summary` to confirm the
    match, record the commit).
  - Else, require that ≥10 functions were triaged AND that the set includes the
    clean-residual cases where candidates DID reach the target register but did
    not improve (genuine "split-doesn't-help" evidence), with budget/cap-exhaust
    cases flagged separately and NOT counted as definitive → **Arm 2**. Write the
    full table into the resolution note so the conclusion is auditable.

## Final verification (before resolving #705)

- [ ] `PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/search/solver/ tools/melee-agent/tests/test_node_set_split.py tools/melee-agent/tests/search/test_cli_smoke.py -q` → green.
- [ ] `python -m compileall -q tools/melee-agent/src` exits 0; `git diff --check` clean.
- [ ] CLI help smoke: `PYTHONPATH=tools/melee-agent python -m src.cli debug solve coloring --help | head -5` works.
- [ ] Land on master + refresh editable install (see resolution checklist).
