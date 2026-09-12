# Select-Order Causal Repair Bridges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
> Keep checklist state current while working.

**Goal:** Resolve issue #844 and issue #845 by turning existing select-order
causal diagnostics into executable or scored source-actionable repair lanes.

**Architecture:** Extend the select-order summary helpers in
`tools/melee-agent/src/cli/debug/__init__.py` and add one small request-parser
extension in `tools/melee-agent/src/mwcc_debug/node_set_split.py`. Add
regression tests before production changes.

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/node_set_split.py`.
- Modify `tools/melee-agent/src/cli/debug/__init__.py`.
- Modify `tools/melee-agent/tests/test_node_set_split.py`.
- Modify `tools/melee-agent/tests/test_select_order_search.py`.
- Commit this plan and its design doc with the implementation.

## Task 1: Owner-Split Node-Set Parsing

**Files:**
- `tools/melee-agent/tests/test_node_set_split.py`
- `tools/melee-agent/src/mwcc_debug/node_set_split.py`

- [ ] Add a red test showing `requests_from_node_set_delta(..., include_introducible=True)` treats a source entry with `kind: "synthetic-owner-split"`, `expression: "dst"`, `type: "u8*"`, and `introduce_binding: true` as an introducible request with `var_name is None`.
- [ ] Update `_request_from_missing_virtual` so `introduce_binding: true` or `source.kind == "synthetic-owner-split"` suppresses `_bindable_source_name`.
- [ ] Verify the red test passes and existing node-set delta parsing tests still pass.

## Task 2: Mixed Source Repair Plan

**Files:**
- `tools/melee-agent/tests/test_select_order_search.py`
- `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] Add a red helper-level test for a Sort targeted-interference plan with IG34 local `dst_iter` and IG44 raw implicit-temp `add r44,r49,r34`, plus IG44 causal owner-split evidence for `dst` as `u8*`.
- [ ] Assert the helper returns `status: "ready"`, a
  `materialized_node_set_delta`, and a `mixed_source_repair_plan` whose IG44
  entry has `safe_source_expression: "dst"` and raw pcode only under
  provenance.
- [ ] Assert the materialized delta parses into coupled requests with target
  IGs `[34, 44]`.
- [ ] Add a red blocker test where the raw implicit-temp entry has no
  owner-split evidence and remains `implicit-temp-not-materializable`.
- [ ] Implement `_select_order_mixed_source_repair_plan` and
  `_select_order_materialized_targeted_interference_delta`.
- [ ] Attach both payloads to `targeted_interference_source_transforms` in
  `_select_order_protected_hit_composition_summary`.

## Task 3: Causal Complement Composition Lane

**Files:**
- `tools/melee-agent/tests/test_select_order_search.py`
- `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] Add a red partial-summary regression for `mnDiagram_DrawCellNumber` with
  protected hits IG33=`f26`, IG39=`f29`, IG40=`f29`; blocked IG32; actionable
  IG38 and IG46 materialized owner-split labels; and a timed-out or
  frontier-limited guard-repair ledger.
- [ ] Include scored candidate fixtures whose chain or source composition
  references IG38 and IG46 materialized labels, and assert the lane reports
  those as `scored_causal_candidates`.
- [ ] Implement `_select_order_causal_complement_composition_lane` using
  `causal_targets`, ranked candidates, and coverage. Preserve all materialized
  labels and classify coverage completeness conservatively.
- [ ] Attach the lane to `protected_hit_composition`.

## Task 4: Verification and Resolution

**Files:**
- All modified files above.

- [ ] Run focused tests:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_owner_split_simple_expression_is_introducible \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_mixed_source_plan_materializes_owner_split_delta \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_mixed_source_plan_blocks_raw_implicit_temp \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_partial_summary_reports_causal_complement_lane \
  -q
```

- [ ] Run narrow suites:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/test_select_order_search.py \
  -q
```

- [ ] Run CLI smoke checks:

```bash
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
melee-agent debug solve node-set-split --help >/tmp/node-set-split-help.txt
melee-agent issues list
```

- [ ] Refresh editable install:

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/opt/python@3.11/bin/python3.11 -c "import src.cli.debug as d; print(d.__file__)"
```

- [ ] Stage only this feature's docs, tests, and implementation hunks. Commit on
  `master`, then resolve #844 and #845 with
  `melee-agent issue resolve <id> --note "fixed in <commit>"`.
