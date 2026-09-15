# Issue 883: Dual-Frontier Protected Expression/Structural Reconciliation

## Scope

Add a bounded reusable reconciliation lane for the retained
`mnDiagram_DrawCellNumber` frontier. The lane consumes two already-retained C
sources:

- an expression-protected source that scores 6/6 by `expression_score` but is
  stuck at `normalized_diff_lines >= 30`, and
- a lower-structural source that reaches about 20 normalized diff lines and
  removes the extra `f25`/frame pressure, but drops the two protected `fsubs`
  expression anchors.

The lane should compose only source subhunks between those two frontiers,
validate every retained candidate with expression anchors, and stop with a
terminal blocker summary if no recombination preserves all anchors while
improving the structural drift threshold.

This is intentionally narrower than a generic source-search system. It is a
protected expression/structural reconciliation lane for retained source pairs
and should fit the existing `mwcc_debug.expression_interferer_repair` and
`debug target score-source` patterns.

## Root Cause

The current tooling has two useful but disconnected frontiers:

- The protected expression frontier preserves the six anchors from
  `build/diagnostics/mndiagram_draw_883_product_hit_target_spec.json`:
  `V33 -> f26`, `V35 -> f26`, `V40 -> f28`, and `V41/V42/V43 -> f29`.
  `score-source` follows source identity, so the 6/6 result is real even when
  virtual IDs renumber. The best source is
  `digit-guard-product-before-count.c`, but the structural guard rejects it
  with `normalized_diff_lines` 30 and a `-176` frame with an extra `f25` save.
- The lower-structural frontier, `combine-fsubs-call0-3dc243d9ff.c`, reaches
  20 normalized diff lines, removes the extra saved `f25`, and computes the
  digit animation call argument directly in `f1` like the target assembly. It
  only scores 4/6 by `expression_score` because the two `fsubs` anchors are
  `missing-expression`.

Existing attempts are exhausted in both directions:

- `melee-agent debug suggest expression-interferer-repair` from the 6/6 source
  generated structure probes and improved 32 to 30 lines, but plateaued without
  crossing below 30.
- Running plan transforms and selected `coloring_register_steering` probes
  from the 20-line source kept the structural shape but did not recover the
  missing `fsubs` expression anchors.
- Issue #884, fixed in `ad1e23b83`, added the focused
  `debug mutate lifetime-layout --focus mixed-pcode-fpr-lifetime` lane for
  mixed pcode/FPR lifetime pressure. Issue #883 should reuse that evidence
  when present but must not reimplement those lifetime pressure probes.

The missing capability is a dual-frontier lane that treats expression identity
as protected, not raw virtual IDs, while trying structural subhunks from the
downhill source in the protected source.

## Existing Capabilities To Reuse

- `melee-agent capabilities search <task>`: audit gate before adding commands.
- `melee-agent debug suggest expression-interferer-repair`: existing
  expression-aware evaluator and source generator. Reuse its policy concepts,
  anchor extraction, terminal summary style, and tests.
- `melee-agent debug target score-source <candidate.c> -f <function>
  --target <target.json> --expression-baseline <baseline.pcdump.txt>
  --expression-source <baseline-source.c> --expression-reg-class fpr
  --checkdiff-guard --json`: authoritative validation path for both
  `expression_score` and `structural_guard`.
- `melee-agent debug search combine` and `debug search minimize`: existing
  hunk merge, manual subhunk, validation diagnostic, and terminal-summary
  vocabulary. The new lane should reuse the same non-overlap/overlap concepts
  but automate the subhunk enumeration for one protected/downhill pair.
- `source_patch.find_function` and the source-hunk helpers already used by
  `expression_interferer_repair.py`: use function-local spans and preserve
  `--source-function` aliasing because master still names this function
  `mnDiagram_80241E78` while diagnostics refer to `mnDiagram_DrawCellNumber`.

## V1 Contract

V1 is generation and ranking over precomputed evidence. It does not run
`score-source` itself.

Inputs:

- `--expression-source`: retained C source for the protected 6/6 frontier.
- `--expression-score-json`: `debug target score-source --json` payload for
  `--expression-source`.
- `--structural-source`: retained C source for the lower-drift frontier.
- `--structural-score-json`: `debug target score-source --json` payload for
  `--structural-source`.
- `--function`: target/report function name.
- optional `--source-function`: function name to patch in retained sources when
  it differs from `--function`.
- `--max-normalized-diff-lines`: structural-improvement threshold, default 30.

The pure module consumes source texts plus score payloads and emits generated
candidate sources, hunk provenance, validation command hints, and a terminal
report. It evaluates generated candidates only when the caller later feeds their
score JSON back into the ranking path. A future wrapper may add an explicit
`--score` mode outside this v1 contract.

`structural_guard.accepted` keeps its existing meaning from checkdiff. It is not
the v1 improvement gate. V1's structural gate is
`structural_improved == normalized_diff_lines < max_normalized_diff_lines`, with
guard acceptance treated as a stronger success. With the default threshold of
30, a candidate at 29 lines improves the plateau, while a candidate at 30 lines
is terminal-ceiling evidence.

Function aliasing:

- candidate files are written with the source function name unchanged;
- validation hints score the source function name because `score-source` accepts
  `--function` only;
- the report carries `target_function` separately for diagnostics.

## Data Model

Add a pure module, for example
`tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`.
Keep command orchestration thin, matching `expression_interferer_repair.py`.

`ExpressionAnchorRequirement`

- `baseline_virtual: int`
- `expected: int`
- `signature: Mapping[str, Any]`
- `label: str | None`
- `required_status: "ok"`

Anchors are keyed by `baseline_virtual` plus signature/source identity from
`expression_score.virtuals`. Candidate virtual IDs are recorded as evidence but
must not be used as the preservation key.

`ReconciliationFrontierSource`

- `frontier_id: str`
- `role: "expression-protected" | "lower-structural"`
- `path: Path`
- `source_text: str`
- `target_function: str`
- `source_function: str`
- `score_payload: Mapping[str, Any] | None`
- `anchors: tuple[ExpressionAnchorRequirement, ...]`
- `expression_matched: int | None`
- `expression_targeted: int | None`
- `structural_guard: Mapping[str, Any] | None`
- `normalized_diff_lines: int | None`
- `frame_size: int | None`

`ReconciliationHunk`

- `hunk_id: str`
- `parent_frontier_id: str`
- `base_start/base_end: int`
- `candidate_start/candidate_end: int`
- `removed: tuple[str, ...]`
- `added: tuple[str, ...]`
- `kind: "statement" | "declaration" | "callarg" | "motion" | "manual-subhunk"`
- `risk: "low" | "medium" | "high"`
- `protected_anchor_overlap: tuple[int, ...]`
- `structural_intent: tuple[str, ...]`

`ReconciliationCandidate`

- `candidate_id: str`
- `source_text: str`
- `applied_hunks: tuple[ReconciliationHunk, ...]`
- `provenance: Mapping[str, Any]`
- `score_payload: Mapping[str, Any] | None`
- `anchor_preservation: Mapping[int, Mapping[str, Any]]`
- `preserved_anchor_count: int`
- `lost_anchor_blockers: tuple[str, ...]`
- `normalized_diff_lines: int | None`
- `frame_improved: bool`
- `structural_improved: bool`
- `structural_guard_accepted: bool`

`ReconciliationReport`

- `status: "success" | "blocked" | "generated" | "scored"`
- `class_id: "protected-expression-structural-reconciliation"`
- `frontiers: Mapping[str, Any]`
- `anchor_requirements: list[dict]`
- `generated_count/scored_count`
- `best_preserving_candidate`
- `best_structural_candidate`
- `terminal_blockers`
- `next_actions`

## Reconciliation Algorithm

1. Load both frontiers and normalize function names.
   Use `--target-function mnDiagram_DrawCellNumber` for scoring metadata and
   `--source-function mnDiagram_80241E78` when patching current master source or
   retained sources that still use address names.

2. Build protected anchor requirements from the expression-protected source's
   `expression_score`. Require every targeted anchor to have `status == "ok"`,
   `matched == true`, and `actual == expected`; reject any
   `false_positive_virtual_id_hit_count > 0`.

3. Diff the expression-protected source against the lower-structural source
   inside the target function. Start from the expression-protected text and
   treat lower-structural hunks as candidate structural imports.

4. Split broad diffs into bounded subhunks using a shared pure hunk helper.
   Use zero-based half-open line coordinates internally and convert to
   one-based ranges only in JSON/human output. The helper must define overlap
   semantics for replacements and zero-width insertions.

   V1 splitting is line-oriented and brace-depth-aware. It may split a broad
   replacement into contiguous statement chunks when each chunk has balanced
   braces, does not start or end inside a brace-depth transition, and does not
   start with preprocessor text or labels. If a changed range contains multiple
   brace-depth transitions or unbalanced braces, emit
   `manual-subhunk-range-required` rather than guessing.

   Statement-level subhunks are enough for this issue: declarations, the
   `digit_count = mn_GetDigitCount(value)` statement, the
   `rowf = (f32) digit` versus direct `(f32) digit` call-argument form,
   product/cast owner statements, row scaling, and the guarded translate calls.

5. Generate a small frontier of composed candidates:
   single subhunks first, then pairs, then triples. Cap defaults should be
   conservative, such as `--max-subhunks 3` and `--max-candidates 64`.
   Prioritize hunks whose structural source removed the fresh digit callarg temp
   or extra `f25`/frame evidence, then product/digit-count ordering hunks, then
   declaration-only hunks.

6. Emit a `debug target score-source` command hint for each generated candidate
   using the source function name, same cflags unit, expression scoring flags,
   and `--checkdiff-guard`. V1 does not execute these commands. A candidate is
   ranked as retained only when the caller supplies matching candidate score
   JSON and all protected expression anchors remain matched by source identity.
   `target_score` raw virtual matches are evidence only.

7. Rank retained candidates by:
   all anchors preserved, `structural_improved`, structural guard accepted,
   lower `normalized_diff_lines`, frame moving toward `-168`, opcode
   similarity, smaller hunk count, then smaller line delta.

8. Stop successfully on the first candidate with 6/6 expression preservation
   and accepted structural guard. If none is guard-accepted, report whether any
   supplied scored candidate dropped below `--max-normalized-diff-lines`.
   Otherwise emit a terminal report after the bounded candidate set is exhausted.

## Terminal Blocker Taxonomy

Use explicit blockers so independent agents can decide whether to continue with
manual matching or tool work:

- `all-recombines-lost-protected-anchors`: every candidate that improves
  structure loses at least one protected expression anchor.
- `structural-ceiling-with-protected-anchors`: at least one candidate preserves
  all anchors, but none improves below `--max-normalized-diff-lines`.
- `fsubs-anchor-structural-incompatibility`: importing the 20-line direct
  callarg shape consistently makes V33/V35 `missing-expression`.
- `direct-callarg-anchor-incompatibility`: preserving V33/V35 consistently
  requires the temp/callarg shape that keeps the structural guard at or above
  30 lines.
- `manual-subhunk-range-required`: broad hunks overlap or cross control
  boundaries and need caller-provided `--range` values.
- `candidate-score-timeout-or-unsafe-lane`: `score-source` refused or timed out
  due to the existing retained-candidate safety checks.

The issue's required terminal stop condition is:
all non-overlapping/subhunk recombines between the two retained frontiers either
lose protected anchors or keep `normalized_diff_lines >= 30`.

## CLI Shape

Add one generation/ranking command under the existing suggest namespace:

```bash
melee-agent debug suggest protected-expression-reconcile \
  --expression-source build/diagnostics/.../digit-guard-product-before-count.c \
  --expression-score-json build/diagnostics/.../digit-guard-product-before-count.json \
  --structural-source build/diagnostics/.../combine-fsubs-call0-3dc243d9ff.c \
  --structural-score-json build/diagnostics/.../combine-fsubs-call0-3dc243d9ff_score.json \
  --function mnDiagram_DrawCellNumber \
  --source-function mnDiagram_80241E78 \
  --cflags-from src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/mndiagram_draw_883_dual_frontier_reconcile \
  --max-subhunks 3 \
  --max-candidates 64 \
  --max-normalized-diff-lines 30 \
  --json
```

The default mode generates probes only and emits score command hints for each
probe. A future `--score` option may run `score-source`, but it is not required
for #883 v1.

## Tests First

Add focused tests before production changes.

1. `tools/melee-agent/tests/test_protected_expression_reconciliation.py`
   - builds synthetic expression/structural sources;
   - verifies anchor requirements are keyed by source identity and baseline
     virtual, not candidate virtual, including renumbering, missing anchors,
     ambiguous signatures, and virtual-ID false positives;
   - verifies hunk coordinates are zero-based half-open internally and one-based
     in reports;
   - verifies zero-width insertions and overlapping replacements are handled
     deterministically;
   - verifies brace/control-boundary rejection emits
     `manual-subhunk-range-required`;
   - verifies direct-callarg import candidates are generated as bounded
     statement subhunks;
   - verifies terminal reports distinguish anchor loss from structural ceiling.

2. Extend `tools/melee-agent/tests/test_expression_interferer_repair.py`
   only if shared anchor-policy helpers move out of that module.

3. Add CLI tests in `tools/melee-agent/tests/test_debug_cli_reorg.py` or a new
   focused CLI test file:
   - `--help` mentions required frontiers, score JSON, target function, and
     source-function aliasing;
   - generation-only mode writes probe files and validation command hints;
   - `--source-function` controls the function patched in retained sources and
     the generated score hints;
   - ranking mode over supplied candidate score JSON reports
     `structural-ceiling-with-protected-anchors` for a 6/6/30 candidate when
     `--max-normalized-diff-lines 30` is used.

4. Preserve existing tests:
   - `PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_expression_interferer_repair.py -q`
   - targeted new reconciliation tests.

## Production Files Likely Touched

- `tools/melee-agent/src/mwcc_debug/protected_expression_reconciliation.py`
  for the pure data model, subhunk generation, preservation gates, ranking, and
  terminal reports.
- `tools/melee-agent/src/mwcc_debug/source_hunks.py` for shared line-based
  hunk primitives with documented coordinate and overlap semantics.
- `tools/melee-agent/src/cli/debug/__init__.py` for the thin
  `debug suggest protected-expression-reconcile` wrapper.
- Tests listed above.

Do not modify the issue #884 mixed lifetime family except to cite it in help or
terminal output as an already-available adjacent lane. The reconciliation lane
should not add new `mixed-pcode-fpr-lifetime` probes.

## Command-Level Smoke

After implementation, run:

```bash
melee-agent debug suggest protected-expression-reconcile --help
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_protected_expression_reconciliation.py -q
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_expression_interferer_repair.py -q
```

For real Draw artifacts, run generation first, then scoring:

```bash
melee-agent debug suggest protected-expression-reconcile \
  --expression-source build/diagnostics/mndiagram_draw_883_six_hit_expression_repair/digit-guard-product-before-count.c \
  --expression-score-json build/diagnostics/mndiagram_draw_883_six_hit_expression_repair/scores/digit-guard-product-before-count.json \
  --structural-source build/diagnostics/mndiagram_draw_883_fsubs_callarg_combine/combine-fsubs-call0-3dc243d9ff.c \
  --structural-score-json build/diagnostics/mndiagram_draw_883_fsubs_callarg_combine/scores/combine-fsubs-call0-3dc243d9ff_score.json \
  --function mnDiagram_DrawCellNumber \
  --source-function mnDiagram_80241E78 \
  --cflags-from src/melee/mn/mndiagram.c \
  --write-probes build/diagnostics/mndiagram_draw_883_dual_frontier_reconcile \
  --max-subhunks 3 \
  --max-candidates 64 \
  --max-normalized-diff-lines 30 \
  --json
```

Then validate retained probes with the emitted `score-source` command hints.
Accept only candidates that keep `expression_score.matched == targeted == 6`
with no false-positive virtual-ID hits.
