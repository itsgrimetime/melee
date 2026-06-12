# Order-class pool census — the directed-class verdict (2026-06-12)

**Worktree:** `.claude/worktrees/mndiagram-802427B4-investigation` (branch
`claude/mndiagram-802427B4-investigation`, HEAD `df0c68e01` — the campaign branch
holding every function's CURRENT BEST form).
**Tooling:** the installed `melee-agent` CLI (editable install resolving to
master's `tools/melee-agent`; `DEFAULT_MELEE_ROOT` resolves to THIS worktree via
its `config/GALE01`, so all builds/probes ran against this worktree's source).
**Derivation CLI:** `melee-agent debug target order-target -f <fn> --json`
(the §4.2 class-partition pipeline; `src/mwcc_debug/order_target_derive.py`).
**Artifacts:** `docs/superpowers/order-targets/census-2026-06-12/` — `<fn>.json`
(the OrderTarget/DeriveInputs JSON; empty for Step-1 exclusions, which exit before
JSON emission), `<fn>.stderr.log` (routing + evidence; the primary evidence for
Step-1 exclusions, force-added past the `*.log` gitignore), `<fn>.yaml` (written
ONLY on a `directed` result — none here), `census_results.json` (durable
machine-readable per-function routing/step/primary/exit summary + headline),
`run_census.sh` (the wall-bounded driver), `baseline_percents.json`.

## Pre-flight (the #580 discipline)

- `melee-agent debug dump doctor` → **PASS** (DLL fresh + deployed + integrity OK;
  `ready for debug dump local`).
- `melee-agent debug dump setup --rebuild-dll` → DLL rebuilt, `mwcceppc_debug.exe`
  patched, pcdump smoke produced 3203 bytes.
- Force-hook engagement → **CONFIRMED**: a scoped forced dump
  (`dump local mndiagram.c --force-iter-first 0:0 --force-iter-first-fn mnDiagram_802427B4`)
  emitted 61 `[FORCE_ITER_FIRST]` log lines (the scope mechanism actively gating
  per function name).
- Baseline sweep → **matches exactly** (report.json fuzzy %, built this worktree):
  OnFrame 99.72, 802427B4 98.84, 802417D0 98.03, 80241E78 98.94, 8023FC28 97.82,
  CursorProc 100 (skipped — matched), UpdateHeader 95.15, AggRank 94.11,
  GetRankedName 97.87, GetRankedFighter 94.58, HandleInput 98.42, 8024227C 95.39.

## The routing pipeline (what each Step decides)

Every outcome is a NAMED routing or a Step-1 classifier exclusion (DATA, never an
error in the impossibility sense). The §4.2 derivation order:

| Step | Gate | Routing on failure |
|------|------|--------------------|
| 1 | checkdiff primary ∈ {`operand-register-or-offset`, `backend-ceiling`, `normalized-structural-match`} (the FULLNORM-0 pure-coloring admission set) | **ValueError** — "not register-only; not in the order-distance pool" (exit 1) |
| 2 | no phys conflict (same virtual → ≥2 target physregs) | `not_order_class` (node-set divergence upstream of select) |
| 3 | ≤64-entry forcing set byte-eliminates | `force_cap_blocked` |
| 4a | forced igs apply at their forced positions | `unstable_target` |
| 4b | **forced-ORDER build byte-eliminates the class residual** | `not_order_class` (order is a symptom of content/emission divergence) |
| 5 | baseline ig-set == forced ig-set | `unstable_target` |
| 6 | ≥2 roles self-reanchor confidently | `unanchorable` |
| 7 | derive-twice DECISIONS hashes match | `unstable_target` |
| — | all gates pass | **`directed`** |

Step 4b is the kill-switch's empirical question: does forcing the retail ORDER
(via `--force-iter-first`) byte-eliminate the residual? If yes → `directed` (a
witness). If no → `not_order_class` (order is downstream symptom).

## Census table

| function | base % | routing | step | key evidence |
|----------|-------:|---------|------|--------------|
| mnDiagram_OnFrame | 99.72 | **not_order_class** (Step-4b; RESOLVED — see Census FINAL) | reaches Step 4b | passed Step 1 (register-only) + Step 2 (no phys conflict) — the ONLY pool fn to reach Step 4b. Phys witness `--force-phys 0:49:28` = byte MATCH ×2 (ig49 `r29`→`r28`); but ALL 8 order forces mismatch (18–108 lines) → order axis does NOT reproduce the target. The census hang was transient (fast on a fresh DLL, #588/#589). |
| mnDiagram_802427B4 | 98.84 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `stack-layout`, not register-only — not in the order-distance pool |
| mnDiagram_802417D0 | 98.03 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `register-allocation`, not register-only — not in the order-distance pool |
| mnDiagram_80241E78 | 98.94 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `stack-layout`, not register-only — not in the order-distance pool |
| mnDiagram_8023FC28 | 97.82 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `data-symbol-or-relocation`, not register-only — not in the order-distance pool |
| mnDiagram_8024227C | 95.39 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `indexed-struct-pointer-materialization`, not register-only — not in the order-distance pool |
| mnDiagram2_UpdateHeader | 95.15 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `instruction-sequence`, not register-only — not in the order-distance pool |
| mnDiagram2_GetAggregatedFighterRank | 94.11 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `instruction-sequence`, not register-only — not in the order-distance pool |
| mnDiagram2_GetRankedName | 97.87 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `indexed-struct-pointer-materialization`, not register-only — not in the order-distance pool |
| mnDiagram2_GetRankedFighter | 94.58 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `indexed-struct-pointer-materialization`, not register-only — not in the order-distance pool |
| mnDiagram3_HandleInput | 98.42 | not_order_class (Step-1 exclusion) | Step 1 | checkdiff primary `instruction-sequence`, not register-only — not in the order-distance pool |

**Step-1 exclusion = "not in the order-distance pool":** the checkdiff primary is
not one of the three FULLNORM-0 pure-coloring primaries. The classifier raises a
`ValueError` (designed Step-1 routing-equivalent, not infrastructure failure;
exit 1, full traceback + the offending primary in each `<fn>.stderr.log`'s
`DeriveInputs(checkdiff_primary=...)` and final `ValueError:` line). Note
`register-allocation` and `stack-layout` SOUND register/coloring-ish but are NOT
in the admission set — they denote diffs with register/stack content that is not
the masked-structurally-zero pure-order residual, so they route out at Step 1.

### Primary distribution of the 10 Step-1 exclusions

| primary | count | functions |
|---------|------:|-----------|
| `instruction-sequence` | 3 | AggRank, UpdateHeader, HandleInput |
| `indexed-struct-pointer-materialization` | 3 | GetRankedFighter, 8024227C, GetRankedName |
| `stack-layout` | 2 | 80241E78, 802427B4 |
| `register-allocation` | 1 | 802417D0 |
| `data-symbol-or-relocation` | 1 | 8023FC28 |

### Note on base-% provenance

The campaign-branch CURRENT BEST forms (this census) differ from the kill-switch
eligibility fixture (`2026-06-12-order-distance-kill-switch-result.md`): the
fixture recorded 802427B4 at 95.68% with primary `signature-type-mismatch`; the
current best form is 98.84% with primary `stack-layout`. Both route out at Step 1
(not register-only). The census uses the current best forms.

## Headline

**0 directed · 11 not_order_class (10 Step-1 exclusions + OnFrame at Step-4b) · 0 #588-blocked · 0 unanchorable · 0 force_cap_blocked · 0 unstable.**

> **UPDATE (2026-06-12, OnFrame ig49 round):** the lone `#588-blocked` cell is
> RESOLVED. The hang was transient (fast on a fresh DLL); OnFrame reaches Step 4b
> and routes `not_order_class` — phys witness exists (`--force-phys 0:49:28` byte
> MATCH ×2) but no order force reproduces it. Census is **FINAL at 0/11 directed**.
> See the "Census FINAL" section below.

- **Directed (kill-switch witness):** 0.
- **not_order_class:** 10 — every one a Step-1 exclusion (checkdiff primary not in
  the FULLNORM-0 admission set `{operand-register-or-offset, backend-ceiling,
  normalized-structural-match}`). None reached the forced-build (Step 4b) gate;
  they are "not in the order-distance pool" by classification.
- **#588-blocked (infra-timeout):** 1 — `mnDiagram_OnFrame`, the SOLE function
  admitted past Step 1 (register-only) AND Step 2 (no phys conflict). Its 1-entry
  forced-union build did not complete on two independent attempts (first >920s,
  second >1060s; operator-killed both times), so its Step-4b verdict (directed vs
  not_order_class) was not obtained — a tooling limit (#588/#589), NOT a routing.

## Consequence

**0 directed results were obtained, so no kill-switch witness is available — but
the empirical refutation is INCOMPLETE, blocked by tooling, not closed by
evidence.** Of the 11 FULLNORM-0 pool functions, 10 are not register-only by
checkdiff classification (`instruction-sequence` ×3, `indexed-struct-pointer-
materialization` ×3, `stack-layout` ×2, `register-allocation` ×1,
`data-symbol-or-relocation` ×1) and route out at Step 1 — their residuals are
content/structure/stack/data divergences, not the pure-coloring order class, so
they belong to the **permuter arm + content-class deep dives**, exactly as the
kill-switch terminal already routed the pool. The single function whose residual
IS register-only (`mnDiagram_OnFrame`, 99.72%, the only one to reach the forced
ORDER probe) could not be decided: its forced-union debug build of `mndiagram.c`
does not return in feasible wall time (#588/#589, reproduced twice at 920s).

Therefore, for the practical FULLNORM-0 pool **as decided by the current
classifier and tooling**: the directed class is **observed-empty (0/11
directed)**, with the lone register-only candidate's verdict gated behind the
#588 union-probe hang rather than refuted. The order-distance premise is
**not affirmatively supported** by this pool — no witness exists — and the
actionable disposition is unchanged from the kill-switch terminal: route the pool
to the permuter arm and content-class deep dives, and do not stand up the Plan C
forced-order pipeline on the strength of this pool. A complete refutation (or the
discovery of a witness) for `mnDiagram_OnFrame` specifically requires fixing #588
(give the collector a real `timeout_s` and/or investigate why one forced-debug
build of `mndiagram.c` exceeds 900s) so its Step-4b forced-build verdict can be
read; until then OnFrame is the one open question, and it is a tooling question.

## Census FINAL — OnFrame resolved `not_order_class` (2026-06-12, OnFrame ig49 round)

The one open cell is now **closed by evidence, not gated by infra.** A follow-up
probe (#588/#589 notes) re-ran the exact hanging command on a freshly
`--rebuild-dll`'d DLL and it **completed in ~2s** — the >920s/>1060s census hang
was **transient** (contended/stale DLL or ninja/repo-lock contention in the
campaign worktree at census time), not an inherent slow path of the
`ig37`/`--diff`/`mndiagram.c` forced build. With the hang removed, OnFrame's
Step-4b verdict is readable, and it routes **`not_order_class`**:

- **Phys witness EXISTS:** `--force-phys 0:49:28 --force-phys-fn mnDiagram_OnFrame`
  → byte-identical MATCH (0 changed lines), reproduced **twice**. The residual is
  a single-node re-color: ig49 (class 0, the inlined `gobj->user_data` temp,
  `lwz r49,44(r32)`) is `r29` in our build, retail wants `r28`. The lone
  mismatch is `+1e0: lwz r28,44(r30)` (retail) vs `lwz r29,44(r30)` (ours),
  inside the inlined `mnDiagram_UpdateScrollArrowVisibility`.
- **NO order force reproduces it (8 variants, all mismatch):** `--force-iter-first 49`
  / `--force-select-order 49` (18 lines), `49,45` / `49,37` / `49,33` (100/108/100),
  the r29 cluster `49,65,47,46,36,34` (92), and the census's `37` / `37,36` / `36`
  / env-fn (108/108/92/108). Moving ig49 up the simplify list perturbs the whole
  high-degree r28/r29/r30/r31 cluster instead of giving ig49 `r28`.

So under the census's strict order-class definition (routing = directed iff a
`force-iter-first` ORDER reproduces the target), **`mnDiagram_OnFrame` routes
`not_order_class`** — the retail `ig49=r28` is a SELECTION/assignment outcome the
order axis does not expose. The census is therefore **FINAL at 0/11 directed**,
with the last cell now a CONCRETE order-class refutation rather than an
infra-blocked unknown. CAVEAT (unchanged): the target is NOT unreachable — it is
a single-node phys re-color provably reproducible via `--force-phys`; the
corresponding C-source question (what makes retail keep that inlined tail temp in
`r28`) is a separate, still-open matching question (see the OnFrame ig49 round in
`CAMPAIGN-STATE-D1COMPLETION.md`: the what-if oracle's only flip lever is the
move-axis = dispense position, which is exactly what the order-force census
cannot reach; the add/remove-edge what-ifs overshoot, and the proven alias
channel CSE'd away at OnFrame's low tail pressure).

## Tooling issues filed

- **#588** — `order-target` Step-3 force-vector union probe hangs with no
  per-probe timeout (`_run_auto_verify_command_with_status` called with
  `timeout_s=None` from the collector at `__init__.py:1827`).
- **#589** (refines #588) — OnFrame's union window is a SINGLE entry
  (`--force-iter-first 37`); the hang is ONE forced-debug build of the large
  `mndiagram.c` TU under wibo + the integrated `--diff` checkdiff, not the
  diagnostic-probe expansion. `mnDiagram_OnFrame` is the only pool function that
  reaches Step 3, so its Step-4b verdict is the single most decision-relevant data
  point and is unobtainable within feasible wall time on the current tooling.

## Reproduction

```bash
cd .claude/worktrees/mndiagram-802427B4-investigation
melee-agent debug dump doctor
melee-agent debug dump setup --rebuild-dll
# per function (each is wall-bounded by `timeout` to survive the #588 hang):
docs/superpowers/order-targets/census-2026-06-12/run_census.sh <fn> [<fn> ...]
```
