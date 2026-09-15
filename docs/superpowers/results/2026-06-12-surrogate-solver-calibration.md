GATE: PASS

# Surrogate-as-Solver — Phase-0 calibration verdict (Task 12, n≥5)

**Plan:** `docs/superpowers/plans/2026-06-12-surrogate-solver-v1.md` Tasks 11+12.
**Spec:** `docs/superpowers/specs/2026-06-12-surrogate-solver-design.md` (rev 3 + Amendments A1 rev 2, A2).
**Computed against commit:** `5bf92b7d9497f01939ff5a6a4abf399ef5cc1a1a` (master), solver
package + fixtures clean at HEAD.
**Verdict:** **5/5 — PASS.** Every gate criterion was verified INDEPENDENTLY by
recomputing it from the frozen artifacts through the PRODUCTION code paths
(`tiebreak.load_ig` / `predict_assignments`, `explain_virtuals`, `probe.*`,
`enumerate_single`, `passes_1_5_filter`, `gate.compare_assignments`) — not by
trusting the recorded `fixture.json` numbers. 128 solver tests pass; the
calibration fixture suite (`test_calibration_t10e_fixtures.py`, 10 tests) RUNS
(not skipped) and passes.

---

## Per-fixture verdict table

| Fixture | Type | Token / outcome | §3 result (predicted-vs-actual) | Pass/Fail |
|---|---|---|---|---|
| `win_cursorproc` (mnDiagram_CursorProc) | win-recovery | alias `gp`/`flow` surfaced; caller-visible | post-IG G1=1.0, **60/60** contested registers predicted == target, `all_match=True` (matches both post-derived AND recorded `phys_target`) | **PASS** |
| `win_80241e78` (mnDiagram_80241E78) | win-recovery | alias `data`/`digit` surfaced; caller-visible | post-IG G1=1.0, **63/63** contested registers predicted == target, `all_match=True` (post-derived AND recorded) | **PASS** |
| `reject_a_gm_80164504` (gm_80164504) | reject-confirmation | `rejected_a` (ig38 first-def `li`, is_runtime_value=False) | n/a (reject) — 8/8 candidates rejected, 0 survivors; audit `reasons=[rejected_a] admits=0` | **PASS** |
| `flag_c_ftPp_SpecialS_0_Coll` (ftPp_SpecialS_0_Coll) | reject-confirmation (class C) | `flagged_c` + window_order quarantine (ig39 r28→r27 uniform callee-save shift) | n/a (flag) — 2/2 flagged, all in `window_order` bucket, 0 full/partial; audit `flags=[flagged_c] admits=0` | **PASS** |
| `reject_b_ftPp_SpecialS_0_Coll` (ftPp_SpecialS_0_Coll, ig55) | reject-confirmation (class B, A2 provenance-KIND) | `rejected_b` (ig55 `implicit-temp`, first-def `addi` → runtime but caller-INVISIBLE by KIND) | n/a (reject) — 8/8 candidates rejected, 0 survivors; audit `reasons=[rejected_b] admits=0` | **PASS** |

All five fixtures are REAL functions (no synthetic stand-ins). The two win
fixtures are self-contained pre/post pairs (phys_target = the post-win build's
actual coloring). The three reject/flag fixtures are whole-function (reject_a,
flag_c) and a real synthetic-intermediate node reused from the frozen flag_c IG
(reject_b, Amendment A2).

---

## Criterion 1 — two win-recoveries (§3 FULL predicted-vs-actual, codex Blocker-2 binding)

Verified independently by loading each frozen `post_win.pcdump.txt`, running the
production `predict_assignments` over the post IG, and asserting the surrogate's
predicted assignment **equals the target on EVERY contested register** via
`gate.compare_assignments` (the "present + matches target" check, NOT node
presence). The recovery is confirmed against both the post-derived `phys_target`
(every observed register of the post IG, spills dropped) and the recorded
`phys_target` in `fixture.json`:

- **win_cursorproc:** post G1 = 1.0, **60 / 60** contested registers match, `all_match=True`.
- **win_80241e78:** post G1 = 1.0, **63 / 63** contested registers match, `all_match=True`.

This is the codex Blocker-2 §3 binding (plan lines 4110-4121): load post-win IG →
`predict_assignments` → assert predicted vector == target on every contested
register. The plan's older node-PRESENCE-only form is NOT what was checked; the
full per-register equality was.

**Note on the test surface:** the existing `test_win_fixture.py` §3 tests
(`test_post_ig_reproduces_target_*`) exercise the §3 helper over a SYNTHETIC
pcdump, so this verdict ran `post_ig_reproduces_target` over the ACTUAL frozen
`post_win.pcdump.txt` artifacts to close that gap directly.

## Criterion 2 — three reject-confirmations (production enumerate+filter, no oracle)

Each via the production `enumerate_single` + `passes_1_5_filter` over the frozen
IG + `bridge.json` source attributions, with the no-oracle recompute-equality
audit (independent `passes_1_5_filter` over the same probe-derived context):

- **reject_a (gm_80164504, ig38):** target first-def opcode `li` → `is_runtime_value=False` → 8 node-add candidates GENERATED, 8 `rejected_a`, 0 survivors into full/partial/window. Audit: `reasons=[rejected_a], admits=0`.
- **flag_c (ftPp_SpecialS_0_Coll, ig39):** `phys_target {39:28}` is a uniform callee-save window shift (r28→r27) → `is_window_order_residual=True` → 2 candidates GENERATED, 2 `flagged_c`, both routed to the `window_order` bucket, 0 in full/partial. Audit: `flags=[flagged_c], admits=0`. (The exit-4 `reason: window-order` negative control is NOT claimed here — per A1 rev 2 §5 it lives in T15's isolated all-window scenario; this is the candidate-level quarantine.)
- **reject_b (ftPp_SpecialS_0_Coll, ig55):** target KIND `implicit-temp`, first-def `addi` → runtime (L2(a) passes) but caller-INVISIBLE by the A2 provenance-KIND rule (`caller_visible_source_of` returns False for synthetic-intermediate kinds) → 8 candidates GENERATED, 8 `rejected_b`, 0 survivors. Audit: `reasons=[rejected_b], admits=0`.

Exact schema tokens (`rejected_a` / `flagged_c` / `rejected_b`) confirmed from the
production predicate path, recompute-equality audited.

## Criterion 3 — broken-filter control (A1 rev 2 §3)

Under the admit-everything filter stub (`broken_filter_admit_everything`), every
reject/flag fixture FAILS its gate predicate — confirmed firing for all three:

- **reject_a:** real filter admits **0** of 8 target candidates; broken filter admits **8** → clean-reject gate predicate (admits==0) FAILS under broken.
- **reject_b:** real filter admits **0** of 8; broken filter admits **8** → FAILS under broken.
- **flag_c:** real filter routes **2/2** to the window bucket; broken filter routes **0** (window-bucket count ≠ candidate count) → quarantine gate FAILS under broken.

## Criterion 4 — WIN-PRESERVATION (the hard invariant; A2's risk)

Independently derived the probe context for the win-recovery alias nodes under the
NEW `probe.py` (fix-l2b: caller-visibility is now a provenance-KIND rule, not
`source is not None`) and confirmed `caller_visible_source=True` for EVERY alias
node — the A2 KIND rule rejects ZERO win-recovery alias nodes:

- **win_cursorproc** (accept `gp`/`flow`): 6 alias nodes in the post IG, all `caller_visible=True` — `flow`/`gp` (`local`), `gp->field_at_0x30` / `gp->field_at_0x2C` / `gp->field_at_0x28` / `gp->field_at_0x24` (`field-load`). Base IG: 0 alias nodes (alias introduced by the win), preservation vacuously holds.
- **win_80241e78** (accept `data`/`digit`): 11 alias nodes in the post IG, all `caller_visible=True` — `data_alias` / `data` (`local`), `digit` / `digit_count` (`call-return`), `data->field_at_0x2C` / `data->field_at_0x28` (`field-load`). Base IG: 4 alias nodes (`digit`/`digit_count` call-returns), all `caller_visible=True`.

Critically, the `field-load` aliases (`gp->field_at_0x2C`, `data->field_at_0x28`)
are admitted: A2 explicitly forbids a `name is None` reject for field-access
aliases because they are realizable alias-introduction levers. The provenance-KIND
rule rejects only synthetic intermediates (`implicit-temp` / `copy/coalesce-product`
/ nameless+lineless `first-def`) and source=None. **No win node falls in that set
→ win-preservation HOLDS.**

## Criterion 5 — paired-trace invariance (reject_b, A2 §4)

reject_b is a REAL exemplar (spec §6: real > planted); §4 paired-trace invariance
is a pass criterion stated "per planted test," and the binding gate criterion for
a real exemplar is the whole-solver reject (Criterion 2), which passes. The
paired-trace machinery was nonetheless exercised in the spec-faithful form: hold
`phys_target` fixed and INJECT one extra node-add plant candidate targeting ig55
into the baseline enumeration, then check the production
`paired_trace_invariance`. Result: `non_plant_identities_unchanged`,
`non_plant_outcomes_unchanged`, `truncated_unchanged`, and
`per_kind_evals_unchanged_modulo_plant` are ALL True → **invariant=True**. (An
earlier attempt that instead CHANGED `phys_target` from `{39:28}` to
`{39:28,55:28}` perturbs `targets_met` — a phys_target-dependent count — and is a
test-construction artifact, not a property violation; §4 pairs runs "on the same
IG" with the plant's own evals the only allowed delta.)

---

## Gate arithmetic

```
frozen + behaving fixtures = 5 of 5
  win_cursorproc                (win-recovery, §3 60/60 all_match)        PASS
  win_80241e78                  (win-recovery, §3 63/63 all_match)        PASS
  reject_a_gm_80164504          (whole-solver rejected_a, audit + §3 ctl) PASS
  flag_c_ftPp_SpecialS_0_Coll   (whole-solver flagged_c + window quar.)   PASS
  reject_b_ftPp_SpecialS_0_Coll (whole-solver rejected_b via A2 KIND)     PASS
needed for the gate          = 5  (2 win-recoveries + 3 reject-confirmations)

GATE: 5/5 — PASS
```

## TRUE proposal-confirmation rate (codex Blocker-2)

Confirmation rate = (win fixtures passing the full §3 predicted-vs-actual check) /
(win fixtures producing a surrogate-winning admitted alias) = **2 / 2 = 100%**.
Denominator n=2 — small, stated honestly; Task 18's pilots extend it with live
builds. Both win fixtures reproduce the winning coloring at post-IG G1=100% on
every contested register.

## 1-hop vs 2-hop decision

- `reject_a_gm_80164504`: `implicated_hops=2` (the constant ig38 is reached via node 40 in the 2-hop set; recorded in FIXTURE_PROVENANCE.md run-5).
- `flag_c_ftPp_SpecialS_0_Coll`: `implicated_hops=1` (single-node residual ig39).
- `reject_b_ftPp_SpecialS_0_Coll`: `implicated_hops=2` (ig55 reachable in the 2-hop set from the `{39:28}` window residual; recorded in run-6).
- Win fixtures: confirmation is the post-IG predicted-vs-target check, independent of the hop radius.

## filter_summary counts per fixture (production enumeration trace, frozen)

| Fixture | candidates_generated | rejected_a | rejected_b | flagged_c | rejected_survival | node-add evals | full/partial/window | truncated |
|---|---|---|---|---|---|---|---|---|
| reject_a_gm_80164504 | 152 | 24 | 0 | 0 | (per trace) | 124 | 0 / 0 / 0 | False |
| flag_c_ftPp_SpecialS_0_Coll | (per trace) | — | — | 2 (target) | — | — | 0 / 0 / 2 | False |
| reject_b_ftPp_SpecialS_0_Coll | 246 | 78 | 40 | 122 | 6 | 122 | 0 / 0 / 122 | False |

(Per-target tallies: reject_a 8/8 rejected_a; flag_c 2/2 flagged_c; reject_b 8/8
rejected_b. The global trace counts are frozen in each `fixture.json`
`whole_solver.enumeration_trace`.)

## Fixture substitutions from Task 10

Two name corrections vs the plan's original `FIXTURES` list, both REAL functions
(no class substitution, no synthetic stand-ins), per the Amendment-A1-rev-2
class ruling and Amendment A2:
- rejected_a: `gm_80164504` (real exemplar; plan originally sketched `mnDiagram2_HandleInput`).
- flagged_c: `ftPp_SpecialS_0_Coll` (real exemplar; plan originally sketched `mnDiagram2_CreateStatRow`).
- rejected_b: `ftPp_SpecialS_0_Coll` ig55 synthetic-intermediate (Amendment A2; closes the dead L2(b) `source is not None` branch with the provenance-KIND rule; plan originally sketched `mnDiagram_80242C0C`, which direct-evidence-excluded).

Full provenance: `tools/melee-agent/tests/fixtures/solver/calibration/FIXTURE_PROVENANCE.md`
(runs 1-6).

---

## Phase 1 status

With `GATE: PASS` (5/5), Phase 1 (Tasks 13-19 — the mechanical preflight, D0
tracked lever catalog, `debug solve coloring` CLI wiring, negative controls,
FPR sweep, pilots, `suggest register-tiebreak` thin-caller conversion) is now
UNBLOCKED. Every Phase-1 task's Step-0 preflight greps line 1 of this doc for the
literal `GATE: PASS` and fails closed otherwise.
