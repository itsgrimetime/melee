# Issue 1106: pcode-only GPR end-pointer/addi source-owner repair

## Scope and constraints

- Planning/design only. Do not edit production or test files in this pass.
- Target checkout reviewed: `/Users/mike/code/melee`.
- The cited issue diagnostics are present under the matcher worktree
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/...`, not under the
  main checkout's `build/diagnostics`. The retained-source fixture should be
  treated as issue-body/matcher-artifact evidence, not as the current
  `src/melee/mn/mndiagram.c` source shape.
- Audit-first check run: `melee-agent capabilities search "pcode-only GPR end-pointer addi temp retained pointer loop source owner repair"`. It found adjacent transform/scoring capabilities, not this exact repair. Use existing transform-corpus/plan-transforms surfaces; do not add a standalone tool.

## Relevant code reviewed

- Transform family registry and Sort plan routing:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`
- Transform materialization orchestration:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_window_order_continuation.py`
- Existing register/indexed-byte GPR families:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`
- Retained/window-order source-owner planner:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/window_order_source.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/test_window_order_source.py`
- `plan-transforms` CLI classification and output/validation summaries:
  - `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`
- Existing end-pointer source-shape precedent:
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/test_pressure_explorer.py`
- Current Sort source shape:
  - `/Users/mike/code/melee/src/melee/mn/mndiagram.c`

## Root cause

The current repair stack has two separate gaps that combine into the reported blocker.

1. The transform-corpus GPR pcode-only families do not model loop bounds/end pointers.
   - `_iter_pcode_only_gpr_address_temp_anchors()` only accepts source shapes like `lhs = base[index]` and optional previous pointer-copy assignments.
   - `_iter_pcode_only_gpr_copy_product_case_c_anchors()` only accepts `for (... owner++ ...)` plus `*owner = ...` store-owner copy-product shapes.
   - Neither recognizes `u8* ll_probe_end_0 = dst + 0x78;` or the paired `ll_probe_iter_0 < ll_probe_end_0` condition as an owner for `addi r34,r40,120`.

2. The retained/window-order source-owner planner sees pcode-only `add/addi`, but its fallback owner ranking is indexed-byte centric.
   - `_implicit_add_owner()` in `window_order_source.py` handles `add/addi` when exactly one operand resolves to a source local, or it emits ranked indexed-byte candidates through `_rank_indexed_byte_source_candidates()`.
   - For issue #1106, IG34 is `addi r34,r40,120`, and IG40 is also pcode-only (`addi r40,r51,28`). That operand chain does not resolve to a single local, so the planner cannot bind the pcode temp to a source owner.
   - Even when source text contains the real owner, `ll_probe_end_0 = dst + 0x78` and the loop condition are not ranked by any current candidate family. Existing diagnostics become `synthetic-temp-operands-unattributed`, `ranked-owner-candidates-not-materializable`, or family-level `source-pattern-not-found`.

The symptom is `node-set-split` reporting `no bindable source variable for ig34`, but the root cause is missing source-owner attribution for retained pointer-loop end bounds. The correct fix is to make the retained source-owner planner materialize end-pointer owner probes for pcode-only GPR `add/addi` chains, then let existing transform-corpus conversion and scoring paths rank them.

## Design decision

Extend the existing retained/window-order source-owner path, not node-set-split and not a new CLI.

The best fit is `window_order_source.py` plus the existing `retained_gpr_case_c_window_order_continuation` / `retained_gpr_case_c_target_live_range_repair` transform-corpus conversion:

- It already owns pcode-only `add/addi` source-owner recovery.
- It already emits `LifetimeLayoutProbe` records that `orchestrator.py` converts to `TransformProbe` records with retained source, pcdump, validation, and `target_score` evidence through `plan-transforms`.
- It already has ranked candidate diagnostics for local/indexed-byte owner materialization, so adding a sibling ranked end-pointer candidate keeps the diagnostic model consistent.

Do not create a new command. A new transform family is optional but not necessary for first implementation. Prefer extending the existing retained GPR Case-C target/window-order families with an explicit `provenance.kind` and metadata:

- `window-order-ranked-end-pointer-source-probe`
- handler: `pcode-addi-end-pointer-owner`
- candidate kind: `pointer-loop-end-pointer`

If review strongly prefers a separate family for reporting, add only a registry family that reuses the same planner output; do not fork the scoring workflow.

## Production changes to implement

1. Add end-pointer candidate discovery in `window_order_source.py`.

   Add a focused scanner near `_rank_indexed_byte_source_candidates()`:

   - Name: `_rank_pointer_loop_end_pointer_candidates(source_text, search_span)`.
   - Recognize C89-safe local pointer end declarations/assignments:
     - `TYPE* end = base + const_or_bound;`
     - `end = base + const_or_bound;`
     - `TYPE* end = base + 0x78;`
   - Pair them with a nearby `for` condition where the end local is the loop bound:
     - `for (...; iter < end; ... iter++ ...)`
     - Optionally accept `end > iter` as lower priority.
   - Record both the owner assignment line and loop header line in the candidate payload.
   - Require:
     - No preprocessor/label/macro-like line.
     - Pointer-looking type or known pointer local.
     - Safe RHS: identifiers/member chains plus integer/hex constants and `+`, no calls, comma, assignment, `++`, `--`, ternary, address-of.
     - Candidate is inside the target function body.
   - Rank exact owner names like `ll_probe_end_*`, `*_end`, and loop condition users before generic pointer arithmetic.

2. Add materialization for end-pointer candidates in `window_order_source.py`.

   Add `_materialize_end_pointer_candidate(...)` alongside `_materialize_indexed_byte_candidate()`:

   - Produce bounded C89-safe variants that perturb the owner without changing meaning.
     The initial implementation only needs the variants required to unblock the
     retained end-pointer owner path:
     - split declaration initializer:
       - `u8* ll_probe_end_0;`
       - `ll_probe_end_0 = dst + 0x78;`
     - assignment base alias, when the end local was declared separately:
       - `u8* window_order_end_base_probe;`
       - `window_order_end_base_probe = dst;`
       - `ll_probe_end_0 = window_order_end_base_probe + 0x78;`
     Offset-alias and loop-condition-alias variants can be added later if
     scoring proves the split/alias probes are insufficient; they are not part
     of this issue's committed scope.
   - Keep edits local to the existing block. Do not move the loop body.
   - Preserve the existing `ll_probe_iter_0` and common-subexpr/coalesce-produced IG44 shape; this family should not rewrite the store owner or common-source r39 probe.
   - Include provenance:
     - `target_ig`, `source_attribution`, original pcode expression, copy chain, base expression, offset expression, end local, iter local, loop header, source spans, and `protected_targets` when available.

3. Wire the end-pointer candidates into `_implicit_add_owner()`.

   - Add `ranked_end_pointer_source_candidates` to `base_metadata`.
   - For `add/addi` implicit temps, always compute both indexed-byte candidates and end-pointer candidates.
   - If operands are unattributed, do not immediately terminalize with only indexed-byte diagnostics. Return metadata containing both ranked lists so `materialize_synthetic_result()` can try end-pointer materialization before declaring `synthetic-temp-operands-unattributed`.
   - Keep indexed-byte first for existing behavior unless the source attribution expression includes a constant byte offset matching an end pointer, such as `addi ...,120`; in that case rank end-pointer candidates first.

4. Extend `materialize_synthetic_result()` in `plan_window_order_source_probes()`.

   Add `materialize_ranked_end_pointer_candidates(...)` parallel to `materialize_ranked_indexed_byte_candidates(...)`:

   - Use a per-target limit, default 1, analogous to `ranked_indexed_byte_candidates_per_target`.
   - Populate diagnostics:
     - `ranked_end_pointer_candidate_diagnostics`
     - `ranked_end_pointer_materialization_summary`
     - `materialized_ranked_end_pointer_source_candidates`
   - If materialized, set `diag["status"] = "materialized"` and clear `terminal_blocker`.
   - If none materialize, leave existing indexed-byte diagnostics intact and use terminal blocker `ranked-owner-candidates-not-materializable`.

5. Preserve transform-corpus conversion and selection priority.

   `_lifetime_layout_probe_to_transform_probe()` already copies provenance fields into payload. Ensure it preserves:

   - `ranked_end_pointer_source_candidate`
   - `synthetic_source_probe.ranked_end_pointer_source_candidates`
   - `source_diff`
   - protected target metadata

   These keys are currently not copied by the explicit payload construction in
   `orchestrator.py`; add them near the existing
   `ranked_indexed_byte_source_candidate` payload copy.

   Also update the window-order probe selection sort in `orchestrator.py` so
   labels beginning `window-order-ranked-end-pointer-` receive the same early
   priority as `window-order-ranked-indexed-byte-`. Without this, the new probes
   can be budget-starved by generic window-order probes before scoring.

6. Update summaries in `search/cli/__init__.py` only if needed.

   The retained target-live-range and window-order summaries already classify transform-corpus probes through validation and `target_score`. Add a small summary hook only if the new provenance is otherwise invisible:

   - Count `retained_gpr...` probes whose payload/provenance kind is `window-order-ranked-end-pointer-source-probe`.
   - Preserve terminal blockers when all end-pointer candidates reject.
   - Do not add new CLI flags.

7. Optional registry metadata update.

   If using the existing families only, update `retained_gpr_case_c_window_order_continuation` and/or `retained_gpr_case_c_target_live_range_repair` metadata strings to mention pcode-only end-pointer/addi owner probes.

   If adding a separate family, name it `retained_gpr_pcode_end_pointer_owner_repair`, restrict to force class 0, route it only for `mnDiagram_SortNamesByKOs` retained contexts, and have it consume the same planner output. This is more visible but has higher registry/test churn; prefer avoiding it unless diagnostics demand a distinct family id.

## Regression tests to write first

1. `tools/melee-agent/tests/search/directed/test_window_order_source.py`

   Add `test_window_order_plan_materializes_pcode_addi_end_pointer_owner()`.

   Fixture:

   ```c
   typedef unsigned char u8;
   void fn(u8* dst, u8* common_source_r39_probe)
   {
       int i;
       {
           u8* ll_probe_iter_0 = common_source_r39_probe;
           u8* ll_probe_end_0 = dst + 0x78;
           for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {
               *ll_probe_iter_0 = dst[i];
           }
       }
   }
   ```

   Source attributions:

   - `34: {"kind": "implicit-temp", "expression": "addi r34,r40,120"}`
   - `40: {"kind": "implicit-temp", "expression": "addi r40,r51,28"}`
   - include any copy-chain fields needed to mirror issue evidence.

   Assert:

   - Plan materializes at least one probe.
   - Probe provenance kind is `window-order-ranked-end-pointer-source-probe`.
   - Diagnostics include `ranked_end_pointer_source_candidates`.
   - Candidate mentions `ll_probe_end_0 = dst + 0x78`.
   - Candidate preserves `ll_probe_iter_0` and does not remove `common_source_r39_probe`.

2. `tools/melee-agent/tests/search/directed/test_window_order_source.py`

   Add `test_window_order_plan_end_pointer_candidate_terminal_blocker_is_specific()`.

   Use a source with a loop header `ll_probe_iter_0 < ll_probe_end_0` but an unsafe end owner, such as `ll_probe_end_0 = get_end();`. Assert:

   - No probes.
   - Diagnostics include rejected end-pointer candidate with reason `unsafe-end-pointer-expression` or `source-expression-not-end-pointer`.
   - Terminal blocker remains `ranked-owner-candidates-not-materializable`, not generic `synthetic-temp-operands-unattributed`.

3. `tools/melee-agent/tests/search/directed/transform_corpus/test_window_order_continuation.py`

   Add a conversion test that feeds a synthetic `LifetimeLayoutProbe` with `provenance.kind = "window-order-ranked-end-pointer-source-probe"` through `_lifetime_layout_probe_to_transform_probe()`. Assert:

   - Family remains `retained_gpr_case_c_target_live_range_repair` or `retained_gpr_case_c_window_order_continuation`, per implementation choice.
   - Payload includes `ranked_end_pointer_source_candidate`, `synthetic_source_probe`, `source_diff`, `protected_targets`, and target assignments `ig34->r27`, `ig44->r25`.

4. `tools/melee-agent/tests/search/test_cli_smoke.py`

   Add `test_plan_transforms_sort_gpr_pcode_end_pointer_owner_probe()`.

   Use temp files for:

   - source text shaped like the retained source lines 935-938.
   - select-order or virtual-explain JSON with IG34/IG40 pcode-only addi attributions and force phys `{34:27, 44:25}`.

   Run the internal `search_app` CLI test runner with:

   - `--function mnDiagram_SortNamesByKOs`
   - `--unit melee/mn/mndiagram`
   - `--force-phys 34:27,44:25`
   - `--source-file <source>`
   - `--virtual-explain-json <json>` or `--select-order-json <json>`, whichever shortest path reaches `plan_window_order_source_probes`
   - `--transform-family retained_gpr_case_c_window_order_continuation`
   - `--write-probes <dir>`
   - `--json`

   Assert:

   - JSON `family_diagnostics` for `retained_gpr_case_c_window_order_continuation` has `materialized_count > 0`.
   - At least one probe payload/provenance contains `ranked_end_pointer_source_candidate`.
   - Written candidate source contains an end-pointer owner perturbation.
   - No family reports `source-pattern-not-found` for this source shape.

5. `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`

   Only if metadata changes:

   - Assert the retained Sort plan still includes existing retained GPR families.
   - If a new family is added, assert it appears for `mnDiagram_SortNamesByKOs` with force phys `{34:27, 44:25}` and has a concrete mutator key or lifetime-probe conversion path.

## Command-level smoke checks after implementation

Run targeted tests first:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/test_window_order_source.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_window_order_continuation.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -k "end_pointer or pcode_end_pointer or window_order_continuation" -q
```

Then run the broader transform-corpus and CLI checks:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -q
```

Manual public command smoke, using the retained-source artifact from the issue
context. Do not pass `--transform-family` to the installed
`melee-agent debug search plan-transforms` smoke unless the installed help shows
that option; the public debug wrapper may expose a reduced option surface even
though the internal `search_app` tests cover family filtering.

```bash
melee-agent debug search plan-transforms \
  --function mnDiagram_SortNamesByKOs \
  --unit melee/mn/mndiagram \
  --force-phys 34:27,44:25 \
  --source-file /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1104_rerun/sort_common_subexpr_bridge/probes/retained_gpr_common_subexpr_coalesce_source@0.c \
  --virtual-explain-json /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1105_rerun/sort_residual_onehit_handoff/explain_virtual/residual_neighborhood.json \
  --max-per-family 8 \
  --write-probes /tmp/issue1106-probes \
  --json > /tmp/issue1106-plan.json
```

Then score generated probes with the existing scorer, not a new tool:

```bash
for f in /tmp/issue1106-probes/*.c; do
  melee-agent debug target score-source \
    "$f" \
    --function mnDiagram_SortNamesByKOs \
    --target /tmp/issue1106-target.json \
    --json
done
```

Success criteria:

- Candidate reaches IG34->r27 while preserving IG44->r25, or the JSON terminal blocker names a specific end-pointer reason.
- Retained source and pcdump/target_score evidence are retained by existing validation/scoring output.
- Existing indexed-byte, GPR address-temp, copy-product Case-C, and retained IG44 tests still pass.

## Design risks and tradeoffs

- The source expression `dst + 0x78` maps to pcode `addi r34,r40,120`, while `dst` itself may be a pcode-derived base (`r40 = r51 + 28`). The planner cannot prove this numeric relationship from C alone unless virtual attribution exposes enough operand chain metadata. The practical design uses source shape plus pcode addi evidence as a ranked owner hypothesis, then relies on target_score validation.
- Loop-header edits are risky. Keep support narrow: only end-pointer locals already used as loop bounds, not arbitrary loop-header local reads.
- Existing pressure-explorer end-pointer probes show viable source forms, but pulling that code directly into `window_order_source.py` would overcouple two planners. Reimplement a small, local scanner/materializer with the same conservative guard style.
- Adding a new family id improves reporting but increases registry, adapter, source catalog, help, and tests churn. Extending existing retained GPR Case-C families is lower risk and keeps the workflow users already have after #1105.
