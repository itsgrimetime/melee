# Calibration fixture provenance (Task 10)

Plan: `docs/superpowers/plans/2026-06-12-surrogate-solver-v1.md` Task 10
(Freeze the FIVE permanent calibration fixtures from REAL functions).

> **STATUS (run-6, 2026-06-12): GATE = 5/5 — PASS.** All five fixtures are frozen
> and behave. The Task-12 verdict is written at
> `docs/superpowers/results/2026-06-12-surrogate-solver-calibration.md` with
> `GATE: PASS` (independently re-verified against the frozen artifacts through the
> production code paths; see that doc). **The "T12 must NOT write GATE: PASS" /
> "GATE still cannot be PASS" directives in the historical run-3/run-4/run-5
> sections below are SUPERSEDED 4/5-era text** — they recorded the gate state at
> those earlier runs (2/5 then 4/5) and no longer hold now that run-6 closed the
> 5th slot (reject_b via Amendment A2). They are retained for the run-by-run audit
> trail; each is annotated inline as SUPERSEDED.

---

## Run-6 (Amendment A2): rejected_b FROZE on a REAL synthetic-intermediate node — GATE 5/5

**Date:** 2026-06-12. **Context:** MASTER (no worktree, no compiler). Amendment
A2 (`docs/superpowers/specs/2026-06-12-surrogate-solver-design.md`) closes the
DEAD L2(b) branch and resolves the run-5 shortfall. Codex review of the
amendment: **SHIP-WITH-CHANGES** (3 implementation prerequisites, all
incorporated — see below).

### The hole (run-5 had it backwards)

Run-5 concluded the Class-B `rejected_b` plant was INFEASIBLE because no win-IG
node has `source=None`. That was the WRONG admission key. The production check
was `caller_visible_source = (source_object is not None)`, and EVERY real traced
node carries at least a `source.expression`, so `caller_visible_source` was
**always True** — the `rejected_b` branch was **DEAD on all real input**, and the
solver would have ADMITTED unrealizable intra-inline node-adds (a copy inside an
inlined body that no caller-level C alias can route through). `source=None` is an
attribution blind spot that does not coincide with a frozen-win-IG node, so the
run-5 plant could never instantiate — but the branch it tested was unreachable
anyway.

### The fix (Amendment A2): provenance KIND, not source-presence / line-range

The brief's literal `source_file`+`source_line` line-range was UNSOUND against
the frozen bridges: `explain_virtuals` threads ONE TU `source_file` into every
node (never distinguishes a same-TU inline), and `source_line` is a grep
heuristic that MISATTRIBUTES in-body locals/params/calls to sibling occurrences
(`popo_gobj`→466, `temp_r31`/`stage_idx`→2215/2216, the in-body
`ftPp_SpecialS_8011F964(popo_gobj)` call at line 957→sibling line 851). A
line-range REJECT would have FALSE rejections.

`probe.caller_visible_source_of(source)` instead makes the provenance KIND the
reject trigger: caller-INVISIBLE (→ `rejected_b`) iff the source is a
compiler-synthesized intermediate with NO source-level variable —
`kind in {implicit-temp, copy/coalesce-product}` OR a nameless+lineless
`first-def` OR no source attribution at all. Everything else is caller-VISIBLE:
named `param`/`local`/`call-return` bindings (the win levers) AND `field-load`s
(field-access aliases like `nana_gobj->field_at_0x2C` are realizable
alias-introduction levers — A2 forbids a `name is None` reject). **Zero false
rejections** (audited against both frozen bridges; the reject set is EXACTLY the
~30 synthetic-intermediate nodes per bridge). The matched-fn
`(source_file, sig_line, end_line)` span is threaded (optional) for diagnostics /
a future tightened in-span ADMIT; the v1 reject needs only the KIND.

### Run-6 fixture: `reject_b_ftPp_SpecialS_0_Coll` (REAL node, NO recompile)

`process_reject_b_from_flag_c` reuses the FROZEN flag_c IG + bridge (the synthetic
node lives in the same IG — no compile, no build lock) and freezes a
self-contained `reject_b_<fn>` dir.

| Field | Value |
|---|---|
| Function | `ftPp_SpecialS_0_Coll` (reuses `flag_c_ftPp_SpecialS_0_Coll` IG/bridge) |
| target_ig | **55** — `implicit-temp`, `expression="addi r55,r54,1"` |
| Why rejected_b | runtime (`addi`, not li/lis → L2(a) PASSES) + synthetic-intermediate KIND (no source variable → L2(b) caller-invisible) |
| implicated_hops | 2 (spec open Q1 widen; ig55 reachable in the 2-hop set from the {39:28} window residual) |
| phys_target | `{39:28}` (the REAL flag_c window residual, reused) |
| Whole-solver | 8 node-add candidates GENERATED, all 8 `rejected_b`, 0 survivors (full/partial/window) |
| Recompute audit | `reasons=[rejected_b], admits=0` |
| §3 broken-filter | admit-everything admits 8/8 (real admits 0/8) → breaks the gate; `audit_equal` real=True/broken=False |
| §4 paired-trace | invariant=True (baseline vs +contest-ig55: non-plant identities/outcomes/truncation/per-kind evals unchanged) |

The full production enumeration trace (246 candidates_generated across the 2-hop
set, rejected_b=40, 122 node-add evals, 0 full/partial, not truncated) is frozen
in `fixture.json`.`whole_solver.enumeration_trace`. The frozen
`base.pcdump.txt` + `bridge.json` let `test_calibration_t10e_fixtures.py`
RE-DERIVE the verdict mwcc-free in CI.

### Codex SHIP-WITH-CHANGES prerequisites — all incorporated

1. **Spec doc hygiene** — pre-A2 text no longer points implementers at 80242C0C
   as the frozen `rejected_b` fixture (annotated SUPERSEDED; 80242C0C kept as the
   L2(b) MOTIVATION only).
2. **probe.py** — `caller_visible_source_of` (KIND gate) + `source_attr_of` (raw
   attribution accessor) added; `derive_probe_context`/`build_probe_ctx_fn` take
   the raw `source`; `source_object is not None` is NO LONGER the L2(b) path
   anywhere (`source_object_of` retained for tooling_leads naming only).
3. **Predicate-level tests** — `test_probe.py` adds named-binding→admit,
   field-load→admit, implicit-temp/copy-coalesce/nameless-first-def/source-None→
   reject, and `source_attr_of` accessor tests; the frozen reject_b fixture
   asserts `candidates_for_target>0` (8) and the whole-solver reject.

### Win-preservation invariant (HARD) — VERIFIED

Every win-lever node (gp/flow, data/digit, new_var) and every realizable-alias
node (field-access alias name=None, named call-return) is `caller_visible=True`
under A2. The reject set is exactly synthetic intermediates + source=None. The
fix rejects ZERO win-recovery nodes. (The win fixtures carry no bridge — they
assert surrogate ranking — so the invariant is enforced on the LOGIC + the
predicate-level tests.)

### Gate arithmetic after run-6

```
frozen + behaving fixtures = 5 of 5
  win_cursorproc              (win-recovery, surrogate-confirmed)        [run-3]
  win_80241e78                (win-recovery, surrogate-confirmed)        [run-3]
  reject_a_gm_80164504        (whole-solver rejected_a, audit + §3 OK)   [run-5]
  flag_c_ftPp_SpecialS_0_Coll (whole-solver flagged_c, audit + §3 OK)    [run-5]
  reject_b_ftPp_SpecialS_0_Coll (whole-solver rejected_b, audit + §3 + §4 OK) [run-6]
needed for the gate         = 5  (2 win-recoveries + 3 reject-confirmations)

GATE: 5/5 — PASS.
```

Test count: 128 solver tests pass (117 baseline + 8 new probe + 3 new reject_b
fixture). The two real exemplars (reject_a, flag_c) RE-DERIVE green under the new
kind-based derivation (no regression).

---

## Run-5 (T10e): final reject-confirmations — 2 REAL exemplars FROZE (whole-solver) + 1 Class-B plant INFEASIBLE (negative coverage reproduced)

**Date:** 2026-06-12. **Context:** the T10e whole-solver harness
(`src/search/solver/calibration_whole_solver.py`) + generator changes + tests
were authored on MASTER; the per-fixture freezes were COMPUTED by running the
updated `generate.py` in the CAMPAIGN WORKTREE
`.claude/worktrees/mndiagram-802427B4-investigation` (HEAD `7098e79f0`, clean,
exclusive — `MELEE_ROOT` resolves to the worktree root, the faithful build
context; deployed DLL intact + hook-bearing, hazard #613's freshness-FAIL
ignored per brief, NO DLL rebuild). The generator + the two helper modules
(`win_fixture.py`, `calibration_whole_solver.py`) were copied into the worktree,
run under the repo build lock, the frozen artifacts (`reject_a_gm_80164504/`,
`flag_c_ftPp_SpecialS_0_Coll/`) harvested to MASTER, and the worktree restored
byte-exact (copied files + win-fixture copies removed; `git status` empty; HEAD
unchanged at `7098e79f0`; baseline `ninja` → 97.58% fuzzy). The artifacts +
generator + harness + tests + this provenance live on MASTER.

### The ruling (orchestrator "Calibration class ruling", A1 rev 2 clause 6, post-mine-rejex)

The corpus query (mine-rejex, `/tmp/rejex-mine-report.md`; 196/354 ≥97% partials
passed direct evidence) resolved the three reject-confirmations to TWO real
exemplars + ONE plant. T10e freezes the two real exemplars as WHOLE-FUNCTION
fixtures (stronger than plants — an independent function + IG + force-phys target
+ a WHOLE-SOLVER reject assertion: the production `enumerate_single` GENERATES
the node-add candidate, the production `passes_1_5_filter` DROPS it) and builds
the one Class-B plant — which is INFEASIBLE on a genuine source=None win-IG node
(the mine-rejex negative coverage, REPRODUCED here).

### Run-5 fixture table

| Fixture | Function | % | real/planted | expected token | frozen? | target_ig | phys_target size | implicated hops | whole-solver reject | recompute audit | broken-filter control |
|---|---|---|---|---|---|---|---|---|---|---|---|
| win_cursorproc | mnDiagram_CursorProc | 100 (post) | real (pre/post) | alias_in_top8 | **YES** (run-3) | — | 60 | — | (win-recovery; surrogate-confirmed all_match) | — | — |
| win_80241e78 | mnDiagram_80241E78 | (post) | real (pre/post) | alias_in_top8 | **YES** (run-3) | — | 63 | — | (win-recovery; surrogate-confirmed all_match) | — | — |
| reject_a_gm_80164504 | gm_80164504 | 99.52 | **REAL** | `rejected_a` | **YES** | 38 (`li r38,0`) | 2 (ig 35,52) | 2 | 8/8 candidates rejected_a, 0 survivors | reasons=[rejected_a], admits=0 | breaks_gate=True |
| flag_c_ftPp_SpecialS_0_Coll | ftPp_SpecialS_0_Coll | 99.88 | **REAL** | `flagged_c` | **YES** | 39 (r27→r28 window) | 1 (ig 39) | 1 | 2/2 flagged_c, all quarantined to window bucket, 0 full/partial | flags=[flagged_c], admits=0 | breaks_gate=True |
| reject_b_plant | (planted over win IG) | — | PLANTED | `rejected_b` | **NO (infeasible)** | — | — | — | — | — | — |

### The two REAL exemplars (whole-solver assertion, A1 rev 2)

**reject_a = gm_80164504 (99.52%, `melee/gm/gm_1601`).** DIRECT-EVIDENCE admitted
(checkdiff primary `normalized-structural-match`; bl-multiset byte-identical,
delta `{added:{}, removed:{}}`; 0 non-register-class normalized diff lines). The
class-signal node is **ig=38** whose frozen first-def opcode is `li` (the
constant `li r38,0`, `explain_virtuals`-confirmed, source-attributed
`source.expression="li r38,0"`). ig=38 is NOT in the force-phys contested
residual {35, 52} (in this build context the constant node is observed r3, which
the surrogate already places on it) but IS in the **2-hop** implicated set of the
residual (1-hop = {35,36,40,44,47,48,50,52}; 2-hop reaches 38 via node 40) — so
the production `enumerate_single` with `implicated_hops=2` (spec open Q1
widen-to-2-hop, cap 64) GENERATES 8 node-add candidates targeting ig=38, and the
production `passes_1_5_filter` REJECTS all 8 as `rejected_a` (is_runtime_value
False ⟸ li first-def), 0 survivors into full/partial/window. The no-oracle
recompute audit (independent `passes_1_5_filter` over the same probe-derived
context) returns exactly `reasons=[rejected_a], admits=0`. The §3 broken-filter
control (admit-everything stub) ADMITS all 8 (vs 0 under the real filter) →
breaks the clean-reject gate. **WHOLE-SOLVER reject assertion: PASS.** Full
production enumeration trace (152 candidates_generated, 24 rejected_a total
across the 2-hop set, 124 node-add evals, 0 hits, not truncated) frozen in
`fixture.json`.`whole_solver.enumeration_trace` (A1 rev 2 §7).

**flag_c = ftPp_SpecialS_0_Coll (99.88%, `melee/ft/chara/ftNana/ftNn_Init`).**
DIRECT-EVIDENCE admitted (`normalized-structural-match`; bl-multiset equal; 0
non-register-class lines). The force-phys residual is a SINGLE node **ig=39**,
observed r27 → desired r28 — a uniform callee-save window shift, so
`probe.is_window_order_residual(ig, phys_target)` is True. The production
enumeration GENERATES 2 node-add candidates targeting ig=39; with
`window_residual=True` the production filter FLAGS them `flagged_c` and routes
BOTH to the `window_order` bucket (candidate-level quarantine, A1 rev 2 §5),
0 into full/partial — never an apply/exit-0 candidate. recompute audit:
`flags=[flagged_c], admits=0`. §3 broken-filter control: admit-everything stops
the flag (candidates not quarantined) → window-bucket count ≠ candidate count →
breaks the gate. **WHOLE-SOLVER flag assertion: PASS.** (The exit-4
`reason: window-order` negative control is NOT claimed by this candidate-level
test — per A1 rev 2 §5 it stays in T15's N-series isolated all-window scenario;
T11 cites that control, this fixture does not duplicate it.)

### Class B (rejected_b) — PLANTED, but INFEASIBLE on a real win-IG node (NEGATIVE COVERAGE, reproduced)

A1 rev 2 §1-2 requires the plant to be an ordinary node-add targeting a win-IG
virtual whose FROZEN attribution has **source=None** (→ `caller_visible_source`
False → `rejected_b`). `process_plant_rejected_b` probes BOTH frozen win IGs
(CursorProc + 80241E78), BOTH register classes (GPR class=0 + FPR class=1), via
the PRODUCTION `explain_virtuals` + `probe.source_object_of` (ig_idx N == virtual
rN, the production mapping):

```
win_cursorproc (mnDiagram_CursorProc): 80 IG nodes probed (class0+class1) — source=None count = 0
win_80241e78   (mnDiagram_80241E78):   95 IG nodes probed (class0+class1) — source=None count = 0
```

**NO source=None virtual exists in EITHER frozen win IG.** This REPRODUCES the
mine-rejex Class-B negative coverage: every traced first-def yields a non-empty
`expression` (a param `gobj`, a local `data`, a call-return `mn_GetDigitAt(...)`,
or even an `implicit-temp` carrying `expression="rlwinm r34,r81,0,24,31"`), so
`probe.source_object_of` is never None → `caller_visible_source` is always True →
the production filter NEVER reaches the `rejected_b` branch via a real win-IG
node. `source_object_of`→None requires the matched `VirtualAttribution` to have
BOTH `name is None` AND `expression is None`, which only happens for a contested
node with NO traceable first-def in the pre-coloring pcode — an attribution-model
blind spot that is intrinsically rare and does not coincide with a frozen-win-IG
node.

Per A1 rev 2 §2 ("if a win IG lacks a qualifying site for a class, that class
runs on the other win IG") AND the task brief ("If NO win-IG virtual has a
genuine source=None node, REPORT that — do not fabricate one — that would force a
spec-relax decision back to the orchestrator"), the generator does NOT fabricate
a source=None node. `process_plant_rejected_b` ABORTS LOUDLY with the negative
coverage recorded. The PURE plant machinery — the no-oracle ProbeContext
derivation, the recompute-equality audit, the broken-filter control, and the
paired-trace invariance check — IS built and unit-tested
(`tests/search/solver/test_calibration_t10e.py`, synthetic source=None node +
synthetic li-constant); ONLY the FROZEN instantiation over a real win IG is
blocked. `_build_rejected_b_plant` is implemented (UNREACHED today) so a future
win IG with a genuine source=None node freezes the plant automatically.

### Gate arithmetic after run-5

```
frozen + behaving fixtures = 4 of 5
  win_cursorproc          (win-recovery, surrogate-confirmed)        [run-3]
  win_80241e78            (win-recovery, surrogate-confirmed)        [run-3]
  reject_a_gm_80164504    (whole-solver rejected_a, audit + §3 OK)   [run-5]
  flag_c_ftPp_SpecialS_0_Coll (whole-solver flagged_c, audit + §3 OK)[run-5]
needed for the gate       = 5  (2 win-recoveries + 3 reject-confirmations)
SHORTFALL                 = 1  (reject_b — Class-B plant infeasible)

GATE: still cannot be PASS (n=4 < 5).   [SUPERSEDED by run-6: reject_b froze on a
                                         REAL synthetic-intermediate node (ig55,
                                         Amendment A2) → GATE 5/5 PASS.]
```

**The shortfall is a SPEC-RELAX decision for the orchestrator**, NOT a
freeze-blocking defect in the two real exemplars (both froze + behave with full
whole-solver assertions). The Class-B reject-confirmation has no real
register-only caller-invisible-split exemplar in the ≥97% pool (mine-rejex) AND
no source=None node in either frozen win IG (reproduced here) — the
production-filter `rejected_b` branch is reachable only from an attribution-model
blind spot that the available frozen artifacts do not contain. Options for the
orchestrator (NONE taken unilaterally per [[never-claim-unmatchable]]):
(a) relax the plant's source=None requirement to a `name is None` + inlined-region
test (a SPEC change — would reclassify expression-sourced inline temps); (b)
freeze a NEW win IG that DOES contain a source=None node and re-run (the plant
machinery auto-freezes it); (c) accept a 4/5 gate with `rejected_b` covered by
the unit-tested pure machinery only (the whole-solver instantiation deferred).

### §7 trace freezing + §4 paired-trace

Each frozen real-exemplar fixture's `fixture.json` carries the full production
enumeration trace (`whole_solver.enumeration_trace`: filter_counts,
evals_per_kind, hit-bucket sizes, truncated, last_kind) for audit (A1 rev 2 §7).
The frozen source-attribution bridge (`bridge.json`, the `explain_virtuals`
`to_dict()`) lets `test_calibration_t10e_fixtures.py` RE-DERIVE the whole-solver
verdict mwcc-free in CI — a corrupt freeze or a production-path regression FAILS
the test rather than trusting the recorded number. Paired-trace invariance (§4)
applies to the PLANT (baseline-vs-planted over a win IG); since the plant is
infeasible to instantiate, the paired-trace check is exercised by the pure unit
tests over synthetic results (`test_paired_trace_*`) rather than a frozen plant.

### Worktree end-state proof (run-5)

`git -C <worktree> status --porcelain` → empty; HEAD unchanged at `7098e79f0`;
baseline `ninja` → 97.58% fuzzy. The copied `generate.py`/`win_fixture.py`/
`calibration_whole_solver.py` and the copied win-fixture dirs (read by the plant
probe) were all removed; the worktree calibration dir is back to its tracked
`README.md` only.

---

## Run-4 (T10d): reject/flag fixtures under DIRECT-EVIDENCE admission — 0/3 admitted (all honestly excluded)

**Date:** 2026-06-12. **Context:** the direct-evidence verdict logic + tests
were authored on MASTER; the per-fixture verdicts were COMPUTED by running the
updated `generate.py` reject path in the CAMPAIGN WORKTREE
`.claude/worktrees/mndiagram-802427B4-investigation` (HEAD `7098e79f0`, clean,
exclusive — `MELEE_ROOT` verified to resolve to the worktree root, the faithful
build context; deployed DLL intact, hazard #613's DLL NOT rebuilt). The updated
`generate.py` + `win_fixture.py` were copied into the worktree, `process_reject`
run for the three reject/flag fixtures under the repo build lock, the verdicts
harvested, the partial `base.c`/`base.pcdump.txt` aborts REMOVED, the copied
files removed, and the worktree restored byte-exact (`git status` empty, HEAD
unchanged, baseline `ninja` → 97.58% fuzzy). The generator diff, the direct-
evidence verdicts, and this provenance live on MASTER.

### The ruling (plan "Calibration admission amendment 2", triage-11 window)

A reject/flag fixture is admitted on DIRECT EVIDENCE — **NOT** the checkdiff
PRIMARY label (#611's identical-multiset FP mislabels two of these
inline-boundary while open):

- **(i) bl-target multiset parity** — the verify-ib REL24 method: extract every
  `R_PPC_REL24 <sym>` / literal `bl <sym>` call edge as a `Counter`; the target
  and current multisets must be byte-identical (no call added, removed, or
  re-pointed). Implemented as `win_fixture._bl_target_multiset` (mirrors
  `debug.py:_bootstrap_target_calls`, keeping multiplicity).
- **(ii) every normalized truth-gate diff line is register-class** — run the
  SAME `checkdiff.normalized_structural_lines` masking (registers→`rN`,
  immediates→`IMM`, labels→`LABEL`, reloc symbols→`RELOC R_PPC_<kind>`), diff
  the two normalized streams, and require ZERO non-register-class hunks. KEY
  INSIGHT: a pure register reassignment VANISHES from the masked space (the two
  bodies normalize identically), so any surviving normalized-diff line is by
  construction NOT register-class — it is an instruction-count (insert/delete),
  an instruction-selection (a `replace` whose mnemonics differ, e.g.
  `addi`→`li`), or a reloc-KIND change. All three are exactly the
  "instruction-count, call-shape, or reloc-symbol" deltas the amendment
  disqualifies. Implemented as `win_fixture.classify_normalized_diff`.

`win_fixture.direct_evidence_verdict` is the pure decision (both checks),
injected `normalized_structural_lines` (checkdiff lives outside the package),
unit-tested mwcc-free in `tests/search/solver/test_win_fixture.py` (4 new tests:
admit-pure-coloring, exclude-on-call-shape, exclude-on-instruction-delta,
classify-register-class-vs-structural). The generator records BOTH the
direct-evidence verdict AND the FP-prone checkdiff primary label in the
abort/fixture record.

### Run-4 verdict table (worktree HEAD `7098e79f0` states)

| Fixture | Function | % | expected token | (i) bl-multiset equal | (ii) all norm lines reg-class | norm diff lines (non-reg/total) | checkdiff primary (FP-prone, NOT used) | VERDICT |
|---|---|---|---|---|---|---|---|---|
| reject_a | mnDiagram2_HandleInput | 97.461 | `rejected_a` | **True** | **False** | 7 / 7 | `inline-boundary-toolchain-artifact` | **EXCLUDED (ii)** |
| reject_b | mnDiagram_80242C0C | 96.951 | `rejected_b` | **True** | **False** | 2 / 2 | `normalized-structural-near-match` | **EXCLUDED (ii)** + SUBSTITUTION flag |
| flag_c | mnDiagram2_CreateStatRow | 83.933 | `flagged_c` | **False** | **False** | 140 / 140 | `inline-boundary-toolchain-artifact` | **EXCLUDED (i)+(ii)** |

**The direct evidence, per fixture:**

- **reject_a (mnDiagram2_HandleInput, 97.461).** (i) PASSES — bl-target
  multisets byte-identical (18 distinct callees, all multiplicities equal; delta
  `{added:{}, removed:{}}`). (ii) FAILS — all 7 normalized diff lines are
  STRUCTURAL, not register-class: an inserted `li rN,IMM` (instruction-count +1),
  a deleted `lbz rN,IMM(rN)` (instruction-count −1), and a 3-line inserted block
  `lwz rN,IMM(IMM)` / `RELOC R_PPC_EMB_SDA21` / `lwz rN,IMM(rN)` (instruction-
  count + a NEW non-sanctioned reloc symbol `mnDiagram2_804D6C18`), plus an
  ADDR16_LO reloc reorder. These are extra constant/SDA materialization, NOT a
  register reassignment. NOTE: the #611 FP labels this `inline-boundary` —
  irrelevant to the verdict; even with #611 fixed it stays excluded on (ii)
  (the extra `li`/`lwz` instructions are a genuine instruction-count delta, not
  the identical-multiset case #611 mislabels). The expected §1.5 `rejected_a`
  (first-def li/lis held-zero constant filtered at enumeration) is NOT reached
  because the function is not register-only — it precondition-fails admission.

- **reject_b (mnDiagram_80242C0C, 96.951).** (i) PASSES — bl-target multisets
  byte-identical (9 distinct callees: `mn_IsFighterUnlocked`×4, `__assert`×8,
  etc., all equal). (ii) FAILS — the **2 historically "near-admission" lines**
  (provenance run-3: "2 normalized lines shy") are an instruction-SELECTION
  change `addi rN,rN,IMM` → `li rN,IMM` (different mnemonic, NOT a register swap)
  AND an instruction-COUNT delta (a deleted `addi rN,rN,IMM`; raw line counts
  321 target vs 320 current). Under the amendment these 2 lines get this
  DIRECT-EVIDENCE verdict rather than the `normalized-structural-near-match`
  label: they are structural, so reject_b is **excluded, not admitted**.
  **SUBSTITUTION QUESTION → ORCHESTRATOR:** reject_b is the caller-invisible-split
  (`rejected_b`) class. Its structural exclusion means a DIFFERENT real function
  with the caller-invisible-split (intra-inline / unresolvable `source` → §1.5
  L2(b) `rejected_b`) property is needed to fill this fixture slot. Per the
  amendment + [[never-claim-unmatchable]], the generator does NOT pick a
  substitute — this is flagged back to the orchestrator. (Candidate-search
  criterion: a register-only-admissible function — direct-evidence (i)+(ii) both
  pass — whose `explain_virtuals` resolves the contested node's `source` to
  None, so `probe.py` derives `caller_visible_source=False` → `rejected_b`.)

- **flag_c (mnDiagram2_CreateStatRow, 83.933, post-string-fix).** (i) FAILS —
  bl-target multisets DIFFER: current emits `HSD_SisLib_803A6368` 4× vs the
  target's 3× (delta `{added:{HSD_SisLib_803A6368:1}}`) — a call-shape delta (an
  extra call edge). (ii) FAILS — 140/140 normalized diff lines non-register-class
  (deeply structural). flag_c cannot reach the `flagged_c`/window_order
  quarantine because that flag (`is_window_order_residual(ig, phys_target)`)
  requires a register-only `phys_target` FIRST — which a 140-norm-line,
  call-shape-divergent function does not have. The expected
  `flagged_c_exit4_window_order` is not reached; the function precondition-fails
  admission. (The post-string-fix `__FILE__`-override win at HEAD `7098e79f0`
  improved 83.241→83.933 but did NOT make the body register-only.)

### Gate arithmetic after run-4

The two WIN fixtures (`win_cursorproc`, `win_80241e78`) remain frozen and
behaving (run-3, both `surrogate-confirmed`/`all_match` on the post IG). Run-4
admits **0 of the 3** reject/flag fixtures under direct evidence.

```
admitted/behaving fixtures = 2 of 5   (win_cursorproc, win_80241e78)
needed for the gate         = 5
GATE: still cannot be PASS  (n=2 < 5)
```

> **SUPERSEDED (run-6).** The run-4 directive below ("T12 MUST NOT write
> `GATE: PASS`") reflected the 2/5 state at run-4. Runs 5 and 6 closed all five
> slots (two real exemplars + the Amendment-A2 reject_b) → GATE 5/5 PASS; the T12
> verdict doc now correctly writes `GATE: PASS`.

T12 MUST NOT write `GATE: PASS`. Three slots remain open; per the amendment they
are filled NOT by these three HEAD states (all structurally excluded by direct
evidence) but by either (a) landing source changes that make these functions
genuinely register-only and re-running, or (b) class-substitutes — for
`rejected_b` specifically, the substitution question above is open with the
orchestrator. No synthetic stand-in was frozen.

### Worktree end-state proof (run-4)

`git -C <worktree> status --porcelain` → empty; HEAD unchanged at `7098e79f0`;
baseline `ninja` → 97.58% fuzzy. The copied `generate.py`/`win_fixture.py` and
the partial reject/flag `base.c`/`base.pcdump.txt` aborts (no `fixture.json` ⟹
placeholders, contract-forbidden) were all removed; the worktree calibration dir
is back to its tracked `README.md` only.

---

## Run-3 (T10c): self-contained pre/post WIN fixtures — 2/2 FROZE; rejects unchanged (still abort)

**Date:** 2026-06-12. **Context:** the CAMPAIGN WORKTREE
`.claude/worktrees/mndiagram-802427B4-investigation`, HEAD `34cd6559c` (clean,
exclusive). The T10c-redesigned `generate.py` + the new pure helper module
`src/search/solver/win_fixture.py` were copied into the worktree, run there
(so `MELEE_ROOT` resolved to the worktree root — the faithful build context;
deployed DLL intact + hook-bearing, hazard #613's stale-DLL-source FAIL ignored
per brief, no DLL rebuild attempted), the win artifacts harvested to master, and
the worktree restored byte-exact (`git status` empty, HEAD unchanged, baseline
`ninja` rebuilt to 97.58% fuzzy). The frozen artifacts + generator + this
provenance live on MASTER.

### The redesign (plan "T10b outcome → BINDING design amendment")

The win fixtures are now **SELF-CONTAINED pre/post pairs**, not base-vs-dol:

1. **`phys_target` := the POST-win build's ACTUAL coloring** (every post-IG
   node's observed register, spill nodes dropped), extracted from
   `post_win.pcdump.txt` in the SAME worktree context — NOT the dol. The win's
   outcome IS that coloring.
2. **Admission is judged on the PRE-vs-POST OBJECT pair** (their diff IS the
   win). Both states are compiled in the worktree (header-locked, `--keep-obj`),
   each function disassembled via the project `dtk`, and the pair classified by
   the SAME `tools/checkdiff.py:classify_asm_diff` arbiter the live register-only
   path uses. **Admission rule = FULLNORM-0** (`normalized_diff_lines == 0`): the
   masked-structural diff (registers/immediates/labels/relocations masked) is
   zero, so every real difference is a register assignment — "pure coloring."
   *Chosen route + why:* this is the mechanically soundest of the amendment's
   options (normalized differ over the two objects). It is NOT the stricter
   `primary in REGISTER_ONLY_PRIMARIES` gate, because BOTH wins carry an 8-byte
   frame-reservation delta (the slot the winning alias/temp local reserves),
   which makes `classify_asm_diff` relabel the primary `stack-layout` even though
   the masked diff is zero. The frame delta is PART of the win (recorded below),
   not noise; `order_target_derive` itself documents FULLNORM-0 as "the pool's
   STRONGEST admission signal," and the surrogate models the *coloring* change,
   which it reproduces at G1=100% on the post IG. (Had T10c used the strict
   primary gate, both wins would have re-aborted as `stack-layout` — the exact
   T10b failure; the amendment's whole point is that POST-collection + FULLNORM-0
   is the faithful gate.)
3. **The frozen artifact carries BOTH IGs:** `base.pcdump.txt` (pre = the
   solver's input), `post_win.pcdump.txt` (post = the gate's re-extraction
   target), plus the post-derived `phys_target` and an `admission` block in
   `fixture.json`. `base.c` / `post_win.c` are the two source revisions.

The PURE decisions (`extract_phys_target_from_ig`, `win_admission_verdict`,
`post_ig_reproduces_target`, `extract_dtk_function`) live in
`src/search/solver/win_fixture.py` and are unit-tested mwcc-free
(`tests/search/solver/test_win_fixture.py`, 7 tests).

### Run-3 verdict table

| Fixture | Function | base→post rev | admission primary | normalized_diff_lines | strict reg-only? | frame (pre→post) | phys_target size | pre/post G1 | re_extract_and_classify |
|---|---|---|---|---|---|---|---|---|---|
| win_cursorproc | mnDiagram_CursorProc | `ea5da317c^1`→`ea5da317c` | stack-layout | **0 (ADMIT)** | no | 96→104 (+8) | 60 | 61/61, 60/60 = 100%/100% | `surrogate-confirmed`, all_match (60/60) |
| win_80241e78 | mnDiagram_80241E78 | `c1aea2d0c~1`→`c1aea2d0c` | stack-layout | **0 (ADMIT)** | no | 168→176 (+8) | 63 | 63/63, 63/63 = 100%/100% | `surrogate-confirmed`, all_match (63/63) |
| reject_a_handleinput_s2 | mnDiagram2_HandleInput | worktree HEAD `34cd6559c` (97.46%) | `inline-boundary-toolchain-artifact` — NOT reg-only | — | — | — | (abort) | — | — |
| reject_b_80242c0c | mnDiagram_80242C0C | worktree HEAD `34cd6559c` (96.95%) | `normalized-structural-near-match` (2 norm lines) — NOT reg-only | — | — | — | (abort) | — | — |
| flag_c_createstatrow | mnDiagram2_CreateStatRow | worktree HEAD `34cd6559c` (83.24%) | `inline-boundary-toolchain-artifact` — NOT reg-only | — | — | — | (abort) | — | — |

**Win fixtures (2/2 froze).** Both PRE-vs-POST object diffs are FULLNORM-0
(`normalized_diff_lines == 0`) — admitted. The post IGs reproduce the winning
coloring at G1=100%, so `gate.re_extract_and_classify` (patched=post,
baseline=pre, the T8-binding actual-vs-target check) returns
`surrogate-confirmed` with `all_match=True` over EVERY contested register (60
for CursorProc, 63 for 80241E78), and `ig_structurally_equal(post, pre)` is
False (the win genuinely changed the graph — CursorProc dropped one node 61→60,
80241E78 kept 63 — so the no-op guard correctly does not fire). The 8-byte
frame growth is the slot the winning alias/temp reserves; it is the reason the
classifier's primary is `stack-layout` rather than `normalized-structural-match`,
and it is exactly why base-vs-dol collection failed in T10/T10b.

**Reject/flag fixtures (UNCHANGED path; re-run to record current verdicts).**
The reject/flag path is byte-unchanged (`collect_target` → the dol-target
register-only collector); per the brief their unblock chain is external (not
forced). Re-run at HEAD `34cd6559c` they ABORT with the same verdicts as the
T10b context-B run: reject_a `inline-boundary-toolchain-artifact`, reject_b
`normalized-structural-near-match` (the 2-line near-admission), flag_c
`inline-boundary-toolchain-artifact`. Per the amendment these clear via (i)
#611 identical-multiset classifier fix (reject_a), (ii) the CreateStatRow
one-extra-call source fix making it genuinely register-only (flag_c), (iii)
re-examination of reject_b's 2-line near-admission under the fixed classifier.
The partial `base.c`/`base.pcdump.txt` written before each abort were REMOVED
(no `fixture.json` ⟹ placeholder; honesty contract). The reject dirs are NOT
frozen.

### Notes for T11 (calibration gate wiring) — the post-derived phys_target

The win `fixture.json` `phys_target` is keyed by **POST-IG** ig indices (the
post coloring). The solver input is the **PRE** IG (`base.pcdump.txt`). The
two index spaces are NOT guaranteed identical (CursorProc post dropped a node,
so pre has an ig index post lacks). T11's `_solve` helper must therefore treat
the win-recovery confirmation as the **post-IG actual-vs-target check** the
amendment defines (load `post_win.pcdump.txt`, `predict_assignments`, assert
`== phys_target` on every contested register via
`gate.re_extract_and_classify` / `compare_assignments` — VERIFIED here to return
`surrogate-confirmed`/`all_match` for both), rather than asserting the
post-space `phys_target` keys exist in the PRE solver-input IG. The §3 step-3
confirmation (codex Blocker-2 residual binding) is satisfied by the post IG;
the plan's older `test_s3_confirmation_on_post_win_artifacts` node-PRESENCE-only
form should be upgraded to the full predicted-vs-target check (the helper
`win_fixture.post_ig_reproduces_target` packages it mwcc-free for that test).
`reachable` is `True` for both win fixtures (FULLNORM-0 admitted + surrogate
reproduces the target). **GATE: still cannot be `PASS`** until all five freeze
and behave (the 3 reject/flag fixtures remain blocked on their external chain).
*(SUPERSEDED by run-6: all five now freeze and behave → GATE 5/5 PASS.)*

### Historical runs (T10 context-A, T10b context-B) — superseded for the WIN class

The sections below record the original base-vs-dol attempts (0/5 in both),
whose root cause (the win base states became frame-gapped `stack-layout`
residuals vs the dol after 114 commits of TU drift) is what the T10c
POST-collection redesign resolves for the two win fixtures. They remain
authoritative for the reject/flag class (whose path is unchanged).

---

Generated by `generate.py` (lock-safe live generator). Two runs were
attempted (the second after the first reported context-A as the blocker):

- **Context-A run (T10):** MAIN checkout `/Users/mike/code/melee`, master HEAD
  `3d616d97a` (2026-06-12). `debug dump doctor` = PASS.
- **Context-B run (T10b):** the CAMPAIGN WORKTREE
  `.claude/worktrees/mndiagram-802427B4-investigation`, branch
  `claude/mndiagram-802427B4-investigation`, HEAD `34cd6559c` (2026-06-12).
  The committed `generate.py` was copied into the worktree fixture tree and run
  there so `MELEE_ROOT` resolved to the worktree root (verified) — every swap,
  dump, checkdiff, and force-phys used the worktree's faithful build context
  (deployed DLL `bc049fe06`, FORCE_PHYS/FORCE_INTERFERE/LIVERANGES hook-bearing;
  IR extraction succeeded for all five, 165K-343K pcdumps). This run was the
  unblock-path-B attempt requested at the Task-12 checkpoint.

## OUTCOME: 0/5 fixtures froze in BOTH contexts — GATE-BLOCKING GAP (honesty contract fired)

In BOTH runs, every fixture ABORTED LOUDLY at the `collect_target`
register-only precondition (`checkdiff_primary not in
REGISTER_ONLY_PRIMARIES`). Per the plan's honesty contract
("ABORT-not-placeholder ... never freeze a placeholder", plan lines 2509-2510,
2483) and "honesty over green" (plan line 4090), NO placeholder fixtures were
frozen in either run. Both runs restored all swapped TUs/headers byte-exact
(try/finally); `git status --porcelain src/` is clean in both checkouts, and
the worktree baseline was rebuilt with `ninja` so its `report.json` reflects
HEAD `34cd6559c`.

This remains a gate-blocking gap at the Task-12 checkpoint, NOT papered over.
T11's calibration gate cannot run (no fixtures); T12 must NOT write
`GATE: PASS`. *(SUPERSEDED by run-6: the fixtures DID freeze in subsequent runs
— two win pre/post pairs (run-3) + two real reject exemplars (run-5) + the
Amendment-A2 reject_b (run-6) — so T11's gate runs and T12 writes GATE: PASS.)*
The context-B run SHARPENED the root cause (below): the
worktree's own build context does NOT reproduce the win base near-match states
either, because the worktree HEAD is **114 commits past** the win-era commits.

## Context-B run (T10b) — verdicts and the sharpened root cause

The brief expected admission ("Win pre-states historically classified
register-allocation — expect admission"). That expectation did NOT hold, for a
concrete, evidence-backed reason. The win commit `ea5da317c` is an **ancestor**
of the worktree HEAD `34cd6559c`, but HEAD is **114 commits ahead of it**
(incl. a master-merge `34cd6559c`); the adjacent TUs diverged (mndiagram2.c
+20, mndiagram3.c +129 lines between `ea5da317c..HEAD`). The win wins were
measured in the contemporaneous (older) build context; swapping only the
historical `.c` + four mn headers into the 114-commits-newer worktree does NOT
reconstruct the win-era inlining/stack environment — the same source-swap
insufficiency the context-A run found for main, now reconfirmed here with a
finer signal.

| Fixture | Function | Unit | Context-B source revision | Dump | Context-B checkdiff primary | truth-gate (norm diff lines) | frame exp/cur (Δ) | reg-only count |
|---|---|---|---|---|---|---|---|---|
| win_cursorproc | mnDiagram_CursorProc | melee/mn/mndiagram | base `f859d407b` (=`ea5da317c^1`) + mn-header swap | OK (2 CG, 165K) | `stack-layout` — NOT register-only | **structural-match (0)** | 104/96 (−8) | 17 |
| win_80241e78 | mnDiagram_80241E78 | melee/mn/mndiagram | base `176c971a8` (=`c1aea2d0c~1`) + mn-header swap | OK (2 CG, 216K) | `stack-layout` — NOT register-only | **structural-match (0)** | 168/176 (+8) | 44 |
| reject_a_handleinput_s2 | mnDiagram2_HandleInput | melee/mn/mndiagram2 | worktree HEAD `34cd6559c` (97.46%) | OK (1 CG, 343K) | `inline-boundary-toolchain-artifact` — NOT register-only | — | — | — |
| reject_b_80242c0c | mnDiagram_80242C0C | melee/mn/mndiagram | worktree HEAD `34cd6559c` (96.95%) | OK (2 CG, 230K) | `normalized-structural-near-match` — NOT register-only | near-zero-structural-diff (2) | — | 40 |
| flag_c_createstatrow | mnDiagram2_CreateStatRow | melee/mn/mndiagram2 | worktree HEAD `34cd6559c` (83.24%) | OK (2 CG, 316K) | `inline-boundary-toolchain-artifact` — NOT register-only | — | — | — |

**Win fixtures — the decisive finding.** Both win BASE (pre-alias) states are
FULLNORM-0 in the worktree: the normalized structural diff is **zero**
(CursorProc 272/272, 80241E78 315/315 masked lines, 0 differing) — the body is
structurally identical to the win-era source. BUT the classifier resolves
`primary` to `stack-layout` because of a **uniform 8-byte frame-reservation
delta** (CursorProc current frame 8 bytes *too small*; 80241E78 current frame 8
bytes *too big*). A frame-size gap is NOT addressable by a `phys_target`
(register reassignment cannot reserve or release a stack slot), so
`stack-layout`'s exclusion from `REGISTER_ONLY_PRIMARIES` is **correct**, not a
mis-classification: the base needs a stack-slot source change (PAD_STACK-class /
address-taken local / lifetime adjustment), which is outside the solver's
force-phys lever class. The 8-byte frame delta is the CONTEXT GAP itself — the
114-commits-newer build environment shifted the frame the win-era `orig/`
target expects.

The win POST states, by contrast, DO reproduce in the worktree (swapped in and
checkdiff'd directly): post `mnDiagram_CursorProc` @ `ea5da317c` →
`instruction-identical` (100% match, the win survives — report.json HEAD also
shows CursorProc=100.0); post `mnDiagram_80241E78` @ `c1aea2d0c` →
`normalized-structural-match` (truth-gate structural-match, 0 norm lines — IN
the register-only set). So the win delta the fixture wants (base register-only
residual → post alias-win) is half-destroyed under context B: the POST is
faithful, but the fixture's force-phys target is collected from the BASE, and
the base regressed to a frame-layout residual.

**Reject/flag fixtures — context-B classifications and the §1.5 expectation
shift.** The worktree's campaign-improved bodies classify differently from
main's much-worse states:
- `reject_a_handleinput_s2`: context-B `inline-boundary-toolchain-artifact`
  (main-run was `signature-type-mismatch`). The §1.5 S2 expectation was
  `rejected_a` (first-def li/lis held-zero constant filtered at enumeration).
- `reject_b_80242c0c`: context-B `normalized-structural-near-match` — a
  near-zero-structural-diff with only **2** normalized diff lines (just shy of
  the 0-line `normalized-structural-match` admission). Main-run was
  `inline-boundary-toolchain-artifact`.
- `flag_c_createstatrow`: stable `inline-boundary-toolchain-artifact` in both
  runs. The §1.5 expectation was `flagged_c_exit4_window_order`.

### Expectation-shift flags for T11 (calibration-doc notes, NOT failures)

Per the brief's instruction ("If a REJECT fixture still fails register-only
admission here, DO NOT force it: record the honest outcome and flag that its
T11 expectation shifts to precondition-abstain instead of filter-reject at
enumeration"): in context B, **all five fixtures abstain at the register-only
precondition** rather than reaching the §1.5 L1/L2 filter or the window-order
bucket. So if T11 were wired to these context-B states:
- **reject_a / reject_b / flag_c:** their §1.5 outcomes (`rejected_a` via
  first-def li/lis; `rejected_b` via source None; `flagged_c_exit4_window_order`
  via window-shift residual) are NOT reached, because the solver
  precondition-abstains BEFORE enumeration (the diffs are structural —
  inline-boundary / near-structural — not register-only). T11's expectation for
  each shifts from "filter-reject/flag at enumeration" to
  **"precondition-abstain (not in the register-only pool)"**.
- **win_cursorproc / win_80241e78:** the BASE precondition-abstains
  (`stack-layout`, frame-reservation residual). The win-recovery confirmation
  (T11/codex binding: load post-win IG → `predict_assignments` → assert
  predicted == `phys_target` for every contested register) cannot be exercised
  from the BASE in this context. The POST states are faithful (see above), so a
  future fixture redesign that collects the target/IG at the POST-win state (or
  that pins the win-era full-tree context) is the path to a real win fixture;
  enacting that is a fixture-design change deferred to the orchestrator (NOT a
  unilateral substitution here).

NO synthetic stand-ins were frozen. The partial `base.c`/`base.pcdump.txt`
artifacts the context-B run wrote before each abort were REMOVED (same as
context A) and the worktree fixture tree restored to its tracked `README.md`.

## Context-A run (T10) — per-fixture provenance + abort table

IR extraction (`debug dump local`) SUCCEEDED for every fixture (valid
COLORGRAPH section, 165K-331K pcdump). The SOLE failing precondition is the
register-only checkdiff gate: each function, built against MAIN's
`orig/GALE01` target, yields a STRUCTURAL diff, not a pure-coloring residual.
A `phys_target` force-phys vector is undefined for a structural diff, so the
gate correctly refuses to freeze.

| Fixture | Function | Unit | Source revision | Dump | checkdiff primary (abort cause) |
|---|---|---|---|---|---|
| win_cursorproc | mnDiagram_CursorProc | melee/mn/mndiagram | base `f859d407b` (=`ea5da317c^1`), post `ea5da317c` (campaign branch) + mn-header swap | OK (1 CG section, 165K) | `stack-layout` — NOT register-only |
| win_80241e78 | mnDiagram_80241E78 | melee/mn/mndiagram | base `176c971a8` (=`c1aea2d0c~1`), post `c1aea2d0c` (campaign branch) + mn-header swap | OK (1 CG section, 216K) | `stack-layout` — NOT register-only |
| reject_a_handleinput_s2 | mnDiagram2_HandleInput | melee/mn/mndiagram2 | current worktree @ `3d616d97a` | OK (1 CG section, 331K) | `signature-type-mismatch` — NOT register-only |
| reject_b_80242c0c | mnDiagram_80242C0C | melee/mn/mndiagram | current worktree @ `3d616d97a` | OK (1 CG section, 230K) | `inline-boundary-toolchain-artifact` — NOT register-only |
| flag_c_createstatrow | mnDiagram2_CreateStatRow | melee/mn/mndiagram2 | current worktree @ `3d616d97a` | OK (1 CG section, 323K) | `inline-boundary-toolchain-artifact` — NOT register-only |

(The frozen `base.c`/`base.pcdump.txt` partial artifacts written before each
abort were REMOVED — committing them without a validated `fixture.json` +
register-only target would itself be the placeholder the contract forbids.)

## Root cause (evidence-backed; MODEL/CONTEXT GAP, never "MWCC quirk")

The target near-match STATES that all five fixtures need do not exist in
current master's build context:

1. **Win fixtures** (`win_cursorproc`, `win_80241e78`): the byte-archived
   pre/post commits `ea5da317c` and `c1aea2d0c` sit ONLY on the campaign branch
   `claude/mndiagram-802427B4-investigation`. Their merge-base with current
   master HEAD is `2f5fb4627` (2026-06-11) — master has since advanced **56
   commits**. `git diff ea5da317c..HEAD` spans **211 files / ~1.88M lines**,
   INCLUDING `tools/mwcc_debug/mwcc_debug.c` (the debug-DLL source, +512 lines)
   and the entire `build/` + `orig/` trees. The "99.52 -> 100" / "98.94 ->
   99.88" wins were measured in that contemporaneous (older) context; the
   campaign-branch function bodies (and their TU inlining environment) do not
   byte-match current master's `orig/GALE01` target, so the residual is
   `stack-layout`, not register-only. Swapping the `.c` + mn headers into
   current master (the zq-probe HEADER-LOCK technique, applied here) is NOT
   sufficient: 56 commits of TU/build divergence cannot be reconstructed by
   source-swap alone.

2. **Reject fixtures** (`reject_a_handleinput_s2`, `reject_b_80242c0c`,
   `flag_c_createstatrow`): the §1.5 reject STATES (S2 held-zero `var_r28`
   constant; intra-inline; window-order) also live in the campaign branch
   worktree and are header-locked. The zq-probe report (2026-06-12, PROBE A)
   already proved the worktree's `mnDiagram2_HandleInput` 97.461% state is "not
   reproducible in main; main's mnDiagram2_HandleInput is a different,
   much-worse state (433 mismatch)". Current master classifies all three as
   structural diffs (signature / inline-boundary), not register-only.

The context-A run concluded that the only remaining path was a generator run
inside the campaign worktree's own build context. The context-B run (T10b)
EXECUTED exactly that (worktree HEAD `34cd6559c`, exclusive build access) and
found the SAME 0/5 outcome — see the "Context-B run" section above. The
sharpened root cause: the worktree HEAD is 114 commits past the win-era
commits, so even its build context no longer reproduces the win base
near-match states (they become FULLNORM-0-but-frame-gapped `stack-layout`
residuals). This is a genuine precondition + context-divergence failure, not a
tooling defect.

## Fresh-upstream re-verification (plan Step 2)

`git fetch upstream` run 2026-06-12. Presence in `upstream/master`:

| Function | upstream hits | worktree hits | note |
|---|---|---|---|
| mnDiagram2_HandleInput | mndiagram2.c (present) | mndiagram2.c (present) | plan said `mnDiagram_HandleInput`/`mndiagram` — that symbol is ABSENT everywhere; see substitution |
| mnDiagram_80242C0C | mndiagram.c=6 | mndiagram.c=5 | present both |
| mnDiagram2_CreateStatRow | mndiagram2.c=3 | mndiagram2.c=3 | present both |
| mnDiagram_CursorProc | mndiagram.c=2 | (campaign) | present upstream |
| mnDiagram_80241E78 | mndiagram.c=7 | (campaign) | present upstream |

No function was matched-and-removed upstream (the #2660 merge did not move
them); all five still appear. The fixtures fail on the register-only
precondition, not on disappearance.

## Substitution (plan Step 2 / honesty contract)

**Fixture 3 — plan transcription correction.** The plan's `FIXTURES` list
(plan lines 2546-2548) names `function="mnDiagram_HandleInput",
unit="melee/mn/mndiagram"`. That symbol does NOT exist in upstream/master or
the worktree (0 hits). The real S2 function — per the spec §6 and the Task 10
brief ("mnDiagram2_HandleInput S2 (rejected_a — constant zero)") — is
`mnDiagram2_HandleInput` in `melee/mn/mndiagram2` (symbols.txt:
`mnDiagram2_HandleInput = .text:0x80243D40`). `generate.py` uses the corrected
name/unit. This is a transcription fix, not a class substitution; the function
is the one the spec/brief intended.

No CLASS substitutions were made (e.g. nearest in-pool register-only partial of
the same expected class): the win fixtures REQUIRE byte-archived pre/post
commits that exist only for these campaign functions, and the reject states are
campaign-worktree-locked. Selecting and verifying substitutes (register-only +
probe.py-classified to the exact reject sub-type, with their own byte-archive
for the win class) is a non-trivial search deferred to the orchestrator.

## Catalog snapshot provenance

`catalog_snapshot/{node-add,edge-add,edge-remove,order}.json` were written
VERBATIM from the `CATALOG_SNAPSHOT` literal in `generate.py` (mwcc-free, no
abort). The lever entries are the §6/§9 levers distilled in the agent memory
dir `/Users/mike/.claude/projects/-Users-mike-code-melee/memory/` — notably
`accessor_macro_inline_frame_lever.md` (anchoring / GET_X accessor frame
lever), `dispform_inline_base_cast_and_per_loop_locals.md` (inline-base-cast,
per-loop-local), `cardstate_iter12_volatile_index_and_decl_chain.md`
(decl-reorder), `comma_expr_defeats_licm_hoist.md`, and the win attributions
(CursorProc gp/flow-alias; 80241E78 loop-tail data_alias + (f32)digit
temp-for-expr). Snapshot date: 2026-06-12. These are tier a (node-add), tier b
(edge-add/remove), tier c (order), matching the §1e "order ranked last" /
census "0/13 order-only byte-eliminates" caveat. T13 promotes this snapshot to
tracked D0.

## What unblocks the gate (for the orchestrator)

Path **(B)** — run inside the campaign worktree's build context — is now TRIED
and EXHAUSTED (the T10b run above; 0/5, same precondition). The remaining
options:

- **(A) — now the primary path.** Land the win states and the reject-state TU
  edits onto MASTER (PR + merge), then re-run `generate.py` in the main
  checkout. CAVEAT learned from T10b: landing the *campaign-branch commit
  bodies* is NOT enough on its own for the WIN fixtures — the base near-match
  is reproduced only when the *contemporaneous* `orig/`/build context is also
  in force. The win POST states reproduce cleanly (CursorProc → 100%
  instruction-identical; 80241E78 → register-only `normalized-structural-match`),
  so the most faithful win fixture is one whose **target/IG is collected at the
  POST-win state** (a fixture-design change: `collect_target` on `post_rev`, the
  alias node already present), confirmed via the T11/codex predicted-vs-target
  check. This is the cleanest unblock and needs an orchestrator decision (it
  changes `generate.py`'s win-fixture collection point).
- **(C)** Substitute five in-pool register-only partials verified against fresh
  upstream — the two win fixtures additionally need byte-archived pre/post
  commits of their own (the reject trio need probe.py to classify them as the
  exact rejected_a/rejected_b/flagged_c sub-types). Per the brief and
  [[never-claim-unmatchable]], NO synthetic stand-ins were frozen here; this
  substitution search is deferred to the orchestrator.

### Recommended next step (T10b verdict)

The win fixtures are recoverable via path (A) with the POST-collection redesign
(strong evidence: both POST states are faithful in the worktree TODAY). The
reject/flag fixtures need either their campaign TU edits landed on master AND
re-classification confirming the §1.5 sub-types, OR class-substitutes. Until
then T12 must NOT write `GATE: PASS`. *(SUPERSEDED by runs 3/5/6: the win
fixtures froze via the POST-collection redesign (run-3) and the reject/flag
slots filled with real exemplars + the Amendment-A2 reject_b (runs 5-6) → GATE
5/5 PASS.)*
