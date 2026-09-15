# Issue #964 Plan: Retained-frontiers Case-C terminal select-order closure

## Scope

This is a planning-only pass. Do not modify production code or tests while
writing this plan.

Target checkout reviewed: `/Users/mike/code/melee`.

The checkout already has unrelated dirty work:

- `tools/melee-agent/src/cli/debug/__init__.py`
- `tools/melee-agent/src/cli/scratch/__init__.py`
- `tools/melee-agent/src/cli/sync/production.py`
- `tools/melee-agent/src/search/solver/solve.py`
- `tools/melee-agent/tests/search/solver/test_solve.py`
- `tools/melee-agent/tests/test_scratch.py`
- untracked `docs/matching-tooling-postmortem-2026-06-15.md`

Preserve those changes. The implementation for this issue should be limited to
the retained-frontier triage library and its tests unless a regression exposes a
missing producer field.

## Reviewed Code

- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - `triage_retained_frontiers()`
  - `_extract_frontiers()`
  - `_walk_mappings()`
  - `_frontier_from_mapping()`
  - `_retained_summary_frontier()`
  - `_merge_frontier()`
  - `_apply_terminal_suppression()`
  - `_continuation()`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/node_set_split.py`
  - `_case_c_order_repair_handoff()`
  - `_node_set_case_c_order_routes()`
- `/Users/mike/code/melee/tools/melee-agent/src/cli/debug/__init__.py`
  - `_select_order_source_bridge_summary()`
  - `_select_order_terminal_exhaustion_summary()`
  - `select_order_search_cmd()`
- `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
  - `_select_order_fpr_case_c_exhaustion()`
  - `_node_delta_force_phys_targets()`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_node_set_split.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_select_order_search.py`
- `/Users/mike/code/melee/tools/melee-agent/tests/test_allocator_ceiling.py`

I also sampled the reported live artifacts from
`/Users/mike/.codex/worktrees/eeff/melee`:

- `build/diagnostics/mndiagram_962_rerun/frontier_triage_after_draw_casec/retained_frontiers.json`
- `build/diagnostics/mndiagram_960_rerun/draw_ig37_resume/node_set_split_resumed.json`
- `build/diagnostics/mndiagram_962_rerun/draw_ig37_select_order_casec/select_order.json`
- `build/diagnostics/mndiagram_962_rerun/draw_aggregate_after_casec/allocator_ceiling.json`

Observed live failure:

- retained-frontiers reports top-level `status == "all-known-frontiers-exhausted"`.
- For `mnDiagram_DrawCellNumber`, it still reports
  `summary.unexhausted_count == 1`.
- The stale frontier is:
  `family_id == "retained-source-select-order-repair"`,
  `kind == "retained-source-select-order-repair"`,
  empty `attempted_targets`, empty `protected_targets`, empty force identity,
  `actionable == false`, and `continuation == null`.
- The originating handoff route in `node_set_split_resumed.json` has the
  missing identity in its command and parent fields:
  `--class 1`, `--target 'r32<r37'`,
  `--transform-force-phys 32:28,37:26,46:26`,
  `target_ig == 37`, `target_reg == "f26"`, retained source, and retained
  pcdump.
- The terminal select-order artifact has:
  `status == "ok"`, `class_id == 1`, `target_orders == [[32, 37]]`,
  `terminal_exhaustion_summary.status == "blocked"`,
  `terminal_exhaustion_summary.kind == "degree-zero-fpr-case-c-source-exhaustion"`,
  `dominant_blocker == "source-probes-exhausted"`,
  `terminal_blocker == "transform-family-exhausted"`,
  `force_phys_targets == {"32": 28, "37": 26, "46": 26}`,
  `blocker_targets == [37]`, and all `force-phys-hit-*` buckets are zero.
- Allocator-ceiling already treats this terminal evidence as meaningful and
  reaches practical-ceiling with the same evidence stack.

## Root Cause

`retained_frontier_triage.py` overgeneralizes retained-summary extraction and
undergeneralizes terminal select-order evidence.

First, `_frontier_from_mapping()` treats any nested mapping whose `kind` starts
with `retained-` or `retained_` as a retained frontier via
`_retained_summary_frontier()`. That catches
`case_c_order_repair.routes[1]`, whose `kind` is
`retained-source-select-order-repair`. That route object is not a summary; it is
a command handoff. Its lane identity lives in the parent handoff and in the
command string, not in `attempted_targets`, `protected_targets`, or
`final_force_phys`. The generic extractor therefore creates an unexhausted
frontier with empty target/force identity and no continuation.

Second, `_frontier_from_mapping()` never extracts
`terminal_exhaustion_summary.kind == "degree-zero-fpr-case-c-source-exhaustion"`
as terminal closure evidence. The terminal summary is emitted by
`debug select-order-search` and is already consumed by allocator-ceiling, but
retained-frontiers does not see it.

Third, `_apply_terminal_suppression()` only has closure families for:

- ADDI copy-product terminals
- C2 sticky-pool terminals
- copy-survived pointer-reset terminals

There is no select-order Case-C terminal suppression family, so even if the
terminal summary were extracted, it would not close the node-set handoff route.

The fix should not filter away "non-actionable with no continuation" frontiers.
That would hide malformed extraction output while leaving the terminal evidence
model incomplete. The correct fix is to model the node-set select-order handoff
and the terminal select-order exhaustion as the same retained-frontier lane.

## Implementation Plan

### 1. Carry parent lane context while walking JSON

Modify `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Change `_walk_mappings()` from yielding only:

```python
(path, mapping, function)
```

to yielding:

```python
(path, mapping, function, context)
```

where `context` is a small dict accumulated from ancestor mappings. Keep this
internal to `retained_frontier_triage.py`; `_extract_frontiers()` is the only
caller that must change.

Context fields to propagate:

- `class_id`
- `target_ig`
- `target_reg`
- `target_reg_num`
- `target_order`
- `target_orders`
- `force_phys`
- `force_phys_targets`
- `source_file`
- `source_retained`
- `pcdump`
- `baseline_pcdump_path`

Use nearest-child override semantics. For example, a
`terminal_exhaustion_summary` child should see the parent select-order
`class_id` and `target_orders`, while the summary's own `force_phys_targets`
should override any parent force field.

Add a private helper:

```python
def _frontier_context(
    mapping: Mapping[str, Any],
    inherited: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ...
```

Keep context values raw. Normalize them only in the frontier-specific
extractors so existing retained summary behavior does not change.

### 2. Extract node-set select-order handoff routes explicitly

Modify `_frontier_from_mapping()` in
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Add a branch before the generic `_is_retained_summary_kind(kind)` branch:

```python
if kind == "retained-source-select-order-repair":
    return _retained_select_order_repair_frontier(
        mapping,
        context=context,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
    )
```

Add `_retained_select_order_repair_frontier()`.

It should:

- Parse the handoff command with `shlex.split()`.
- Extract `-f`/`--function`, `--class`, `--target`, `--source-file`, `--pcdump`,
  `--force-phys`, and `--transform-force-phys` from the command as fallback
  values.
- Prefer context fields over command-derived fields when present.
- Normalize `force_phys` from either a mapping or CSV string such as
  `32:28,37:26,46:26`.
- Normalize target orders from either `target_orders == [[32, 37]]`,
  `target_order == "r32<r37"`, or command `--target`.
- Parse `target_reg == "f26"` or `"r26"` into `26` when `target_reg_num` is not
  present.
- Build `attempted_targets` from `target_ig` plus target phys when available.
  For the reported route this should be `{"37": 26}`.
- Build `protected_targets` as `final_force_phys - attempted_targets`. For the
  reported route this should be `{"32": 28, "46": 26}`.
- Set `final_force_phys` to the normalized full force map.
- Use a canonical frontier id that can also be produced by terminal
  select-order summaries:

```python
frontier_id = _frontier_id(
    function,
    "retained-source-select-order-repair",
    ("class", class_id),
    ("target_orders", normalized_target_orders),
    ("force", final_force),
)
```

- Set:
  - `family_id = "retained-source-select-order-repair"`
  - `kind = "retained-source-select-order-repair"`
  - `suppression_family = "select-order-case-c-source-exhaustion"`
  - `select_order_signature = _json_key((class_id, normalized_target_orders, final_force))`
  - `class_id = class_id`
  - `target_orders = normalized_target_orders`
  - `source_file = source_file`
  - `pcdump = pcdump`
  - `continuation = {"route": "command-hint", "command": command}`
  - `actionable = True` when the command exists and the route is not terminal

This fixes the pre-terminal state too: a handoff route by itself should be an
actionable next frontier, not an open non-actionable record with no
continuation.

### 3. Extract terminal select-order exhaustion summaries

Modify `_frontier_from_mapping()` in
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Add a branch before the generic retained-summary branch:

```python
if (
    key == "terminal_exhaustion_summary"
    and mapping.get("kind") == "degree-zero-fpr-case-c-source-exhaustion"
):
    return _select_order_case_c_terminal_frontier(
        mapping,
        context=context,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
    )
```

Add `_select_order_case_c_terminal_frontier()`.

It should:

- Require `status == "blocked"`.
- Require a non-empty normalized `force_phys_targets`.
- Use context `class_id` and `target_orders` from the parent select-order JSON.
  For this specific kind, `class_id` should normally be `1`; do not require it
  if old artifacts are missing the field.
- Normalize `blocker_targets`. Use those as `attempted_targets` when they map
  into `force_phys_targets`. For the reported artifact this should be
  `{"37": 26}`.
- Use the remaining force targets as `protected_targets`.
- Use the same canonical frontier id shape as the route extractor:

```python
frontier_id = _frontier_id(
    function,
    "retained-source-select-order-repair",
    ("class", class_id),
    ("target_orders", normalized_target_orders),
    ("force", final_force),
)
```

- Set:
  - `family_id = "retained-source-select-order-repair"`
  - `kind = "degree-zero-fpr-case-c-source-exhaustion"`
  - `terminal = True`
  - `terminal_reason = terminal_blocker or dominant_blocker or kind`
  - `suppression_family = "select-order-case-c-source-exhaustion"`
  - `select_order_signature = _json_key((class_id, normalized_target_orders, final_force))`
  - `continuation = None`
  - `actionable = False`
- Preserve useful summary metrics in `metrics`, including:
  - `dominant_blocker`
  - `terminal_blocker`
  - `blocker_targets`
  - `diagnostic_bucket_counts`
  - `best_retained_variant_count`
  - `next_source_lever_classes`

Do not change `debug select-order-search` initially. Its JSON already contains
the necessary parent fields (`function`, `class_id`, `target_orders`) and the
terminal summary contains the force and blocker targets.

### 4. Add select-order terminal suppression

Modify `_apply_terminal_suppression()` in
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Add:

```python
select_order_case_c_terminals = [
    frontier for frontier in frontiers
    if frontier.get("terminal")
    and frontier.get("suppression_family") == "select-order-case-c-source-exhaustion"
]
```

Then close matching non-terminal select-order handoff frontiers with
`_close_frontier()`.

Add helpers:

```python
def _is_select_order_case_c_suppressible(frontier: Mapping[str, Any]) -> bool:
    ...

def _select_order_case_c_matches(
    frontier: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    ...
```

Matching rules:

- Same function is required.
- Same `suppression_family` is required.
- If both sides have `class_id`, they must match.
- Full normalized force maps must match.
- If both sides have non-empty normalized `target_orders`, they must match.
- If one side lacks target orders, fall back to requiring force equality plus
  intersection between terminal `blocker_targets` and the frontier's attempted
  targets.
- Do not require exact source-file or pcdump path equality. Existing artifacts
  mix absolute and relative paths and may cross worktrees; force plus target
  order is the stable route identity.

This suppression path is a fallback. In the normal case the route and terminal
will already share the same `frontier_id` and merge directly.

### 5. Make merge order deterministic

Modify `_merge_frontier()` in
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`.

Current behavior marks `suppressed_by_terminal` only when an existing
non-terminal frontier receives an incoming terminal frontier. If the terminal
artifact is discovered first, and the matching route is discovered later with
the same canonical id, the result remains terminal but may not count as
suppressed.

Update merge behavior:

- If `existing["terminal"]` is already true and `incoming["terminal"]` is false
  for the same `frontier_id`, keep the existing terminal state, keep
  `actionable = False`, keep `continuation = None`, and set
  `suppressed_by_terminal = True`.
- Preserve the terminal artifact in `closed_by`.
- Add incoming non-terminal artifact to a non-public debug field only if useful,
  not to `closed_by`; `closed_by` should name terminal evidence.
- Continue merging metrics, `class_id`, `target_orders`, `select_order_signature`,
  and source/pcdump metadata when present.

This keeps `suppressed_by_terminal_count` stable regardless of filesystem scan
order.

### 6. Add small normalization helpers

Add the following private helpers to
`/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`:

- `_normalized_force_phys(value: Any) -> dict[str, int]`
  - Accept mappings and CSV strings.
  - Support `IG:PHYS`.
  - Optionally tolerate class-scoped `CLASS:IG:PHYS` by using the last two
    fields as IG and phys.
- `_normalized_target_orders(value: Any) -> tuple[tuple[int, int], ...]`
  - Accept list pairs, tuple pairs, or CSV strings like `r32<r37,r46<r37`.
- `_command_option(parts: Sequence[str], *names: str) -> str | None`
  - Handles `--flag value` and `--flag=value`.
- `_register_num(value: Any) -> int | None`
  - Parses `26`, `"26"`, `"f26"`, and `"r26"`.

Keep these local to retained-frontier triage. Do not import CLI parsers from
`src.cli.debug.__init__`; that file is large and currently dirty in the shared
checkout.

## Regression Tests

Modify only `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`.

Add helper fixtures:

- `_draw_node_set_select_order_handoff(tmp_path)`
  - Mimics `node_set_split_resumed.json`.
  - Includes `function == "mnDiagram_DrawCellNumber"`.
  - Includes `case_c_order_repair.kind == "fpr-pcode-temp-case-c-order-repair"`.
  - Includes parent `class_id == 1`, `target_ig == 37`, `target_reg == "f26"`,
    `force_phys == "32:28,37:26,46:26"`, `target_order == "r32<r37"`,
    source file, pcdump, and a route with
    `kind == "retained-source-select-order-repair"`.
- `_draw_select_order_case_c_terminal()`
  - Mimics `select_order.json`.
  - Includes top-level `function`, `status == "ok"`, `class_id == 1`,
    `target_orders == [[32, 37]]`.
  - Includes `terminal_exhaustion_summary.status == "blocked"`,
    `kind == "degree-zero-fpr-case-c-source-exhaustion"`,
    `dominant_blocker == "source-probes-exhausted"`,
    `terminal_blocker == "transform-family-exhausted"`,
    `force_phys_targets == {"32": 28, "37": 26, "46": 26}`,
    `blocker_targets == [37]`, and zero `force-phys-hit-*` bucket counts.

Add these tests:

1. `test_node_set_select_order_handoff_is_actionable_before_terminal`
   - Inputs: handoff artifact only.
   - Asserts top-level `status == "actionable"`.
   - Asserts `next_frontier.family_id == "retained-source-select-order-repair"`.
   - Asserts `next_frontier.actionable is True`.
   - Asserts `next_frontier.continuation.route == "command-hint"`.
   - Asserts the command contains `debug select-order-search`.
   - Asserts `attempted_targets == {"37": 26}` and
     `protected_targets == {"32": 28, "46": 26}`.
   - Validates the route is no longer extracted as an empty non-actionable
     frontier.

2. `test_select_order_terminal_exhaustion_closes_node_set_handoff_route`
   - Inputs: handoff artifact plus terminal select-order artifact.
   - Asserts top-level `status == "all-known-frontiers-exhausted"`.
   - Asserts function `frontiers == []`.
   - Asserts `next_frontier is None`.
   - Asserts `summary.unexhausted_count == 0`.
   - Asserts `summary.terminal_count == 1`.
   - Asserts `summary.suppressed_by_terminal_count == 1`.
   - Asserts the terminal frontier has:
     - `terminal is True`
     - `suppressed_by_terminal is True`
     - `terminal_reason == "transform-family-exhausted"`
     - terminal artifact path in `closed_by`
     - `attempted_targets == {"37": 26}`
     - `protected_targets == {"32": 28, "46": 26}`
   - Validates the exact #964 failure shape.

3. `test_select_order_terminal_exhaustion_does_not_close_mismatched_handoff`
   - Inputs: handoff with force `32:28,37:26,46:26`, terminal with either
     different `target_orders` or different `force_phys_targets`.
   - Asserts top-level `status == "actionable"`.
   - Asserts the handoff remains in `frontiers`.
   - Validates suppression is scoped and does not close unrelated retained
     routes for the same function.

4. `test_retained_frontiers_cli_select_order_terminal_exits_3`
   - Use `CliRunner` against `search_app`, with `_compute_melee_root`
     monkeypatched to `tmp_path`.
   - Pass the two artifacts explicitly with `--artifact`.
   - Assert exit code `3`.
   - Assert JSON output has `status == "all-known-frontiers-exhausted"` and
     `unexhausted_count == 0`.
   - Validates the user-facing command behavior that matcher loops depend on.

Do not change `tools/melee-agent/tests/test_select_order_search.py` unless the
implementation reveals that the select-order producer must emit additional
identity. Based on review, it already emits enough.

## Validation

Run focused tests:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_retained_frontier_triage.py -q
```

Run adjacent allocator-ceiling and select-order regressions:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_allocator_ceiling.py::test_draw_force_vector_no_match_after_coupled_exhaustion_is_practical_ceiling \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_terminal_exhaustion_reports_case_c_no_hit \
  -q
```

If the exact select-order test name differs, use:

```bash
cd /Users/mike/code/melee
PYTHONPATH=tools/melee-agent pytest --no-cov \
  tools/melee-agent/tests/test_select_order_search.py -k terminal_exhaustion -q
```

Run syntax validation:

```bash
cd /Users/mike/code/melee
python -m py_compile tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py
```

Smoke the live #964 evidence:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
melee-agent debug search retained-frontiers \
  -f mnDiagram_DrawCellNumber \
  -a build/diagnostics/mndiagram_960_rerun/draw_ig37_resume/node_set_split_resumed.json \
  -a build/diagnostics/mndiagram_962_rerun/draw_ig37_select_order_casec/select_order.json \
  --json
```

Expected smoke result:

- top-level `status == "all-known-frontiers-exhausted"`
- `functions[0].summary.unexhausted_count == 0`
- `functions[0].summary.terminal_count >= 1`
- `functions[0].summary.suppressed_by_terminal_count >= 1`
- `functions[0].frontiers == []`
- `functions[0].next_frontier == null`
- a terminal frontier includes `terminal_reason == "transform-family-exhausted"`
  and the select-order artifact in `closed_by`

Then rerun the broader reported scan:

```bash
cd /Users/mike/.codex/worktrees/eeff/melee
melee-agent debug search retained-frontiers \
  -f mnDiagram_DrawCellNumber \
  -a build/diagnostics/mndiagram_960_rerun/draw_ig37_resume/node_set_split_resumed.json \
  -a build/diagnostics/mndiagram_962_rerun/draw_ig37_select_order_casec/select_order.json \
  -a build/diagnostics/mndiagram_962_rerun/draw_aggregate_after_casec/allocator_ceiling.json \
  --json
```

Expected result remains `all-known-frontiers-exhausted` with no unexhausted Draw
frontiers.

## Non-goals

- Do not suppress all non-actionable frontiers globally.
- Do not change allocator-ceiling for this issue; it already recognizes the
  terminal select-order evidence.
- Do not change select-order search output unless tests prove that parent
  context is unavailable. The current JSON already has the required identity.
- Do not require path equality between route and terminal artifacts. Match on
  function, class, normalized target orders, and normalized force targets.
