# Inline Call-Return Owner Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to execute this plan task by task.
> Keep all documentation and code uncommitted until root review.

**Goal:** Extend the existing window-order call-return planner so a uniquely
proven TU-local inline wrapper maps a low-level return copy chain to its visible
caller owner and yields one bounded source probe.

**Architecture:** Add a fail-closed tree-sitter-backed resolver beside the
current call-return owner logic in `window_order_source.py`. Direct named-owner
behavior remains first. The fallback proves the helper call/local/return chain,
pointer types, target assignment, and copy chain, then reuses the current owner
split materializer and campaign orchestration. It emits no new command, search
family, artifact format, or unproven source guess.

**Tech stack:** Python 3, existing tree-sitter-c bootstrap and statement-group
model, existing `LifetimeLayoutProbe`/select-order pipeline, pytest, Ruff,
compileall.

## Global constraints

- Preserve exact source attribution verbatim in every emitted probe.
- Resolve no more than one wrapper owner and emit no more than one candidate
  per unique chain.
- Require a bounded target-to-r3 copy chain and exact source pointer-type
  compatibility.
- Abstain on duplicate definitions, repeated calls, multiple returns, macros,
  preprocessor control, compound expressions, casts, and unsafe spans.
- Record one concrete rejection reason per unique chain.
- Add no new CLI option or third-party dependency.
- Use `apply_patch` for edits and leave the worktree uncommitted for root review.

### Task 1: Specify the resolver with failing unit tests

**Files:**

- Modify: `tools/melee-agent/tests/search/directed/test_window_order_source.py`

- [ ] Add a minimal positive fixture containing a `static inline HSD_JObj*`
  helper, one `result = HSD_JObjLoadJoint(...)`, one `return result`, and one
  target `header = helper(...)`. Attribute target IG 72 as `call-return` with
  null name/type and `copy_chain=[72, 86, 3]`.
- [ ] Assert exactly one probe, `owner_local=header`, wrapper/result/call/return
  provenance, `candidate_limit=1`, unchanged original source attribution, and
  the existing caller-side synthetic split.
- [ ] Add parameterized negative fixtures/assertions for two eligible wrappers,
  repeated relevant calls, repeated target calls, multiple returns, a compound
  target RHS, missing owner/helper pointer type, incompatible type, invalid
  copy chain, duplicate helper definition, and preprocessor/macro ambiguity.
- [ ] Assert each negative lead has zero probes, one exact
  `rejection_reason`, and the same value in `terminal_blocker`.
- [ ] Run:
  `cd tools/melee-agent && pytest tests/search/directed/test_window_order_source.py -k 'inline_call_return' -q`
  and confirm the positive and exact-reason tests fail before production code.

### Task 2: Implement conservative inline-wrapper resolution

**Files:**

- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`

- [ ] Add an immutable internal resolution record carrying the visible owner,
  wrapper/result/type/source-span proof, exact copy chain, and JSON-safe
  metadata.
- [ ] Add a bounded tree-sitter walk/local helper set that:
  identifies unique function definitions; extracts a normalized inline pointer
  return type; finds one exact low-level call assignment; proves one direct
  return of the same local; and rejects preprocessor/macro/parse ambiguity.
- [ ] Add target scanning that considers only simple bare-call assignments from
  existing sibling groups, resolves the visible owner pointer type, and accepts
  exactly one helper/assignment pair.
- [ ] Validate wrapper fallback provenance: call-return kind, string
  `call_symbol`, distinct integer copy chain, first IG equal to the selected
  target, last IG equal to 3, and a small fixed maximum chain length.
- [ ] Update `_call_return_owner_split` to preserve the direct named-owner path,
  invoke the fallback only when needed, and return the proven owner with
  `resolution=inline-wrapper-return-owner` metadata.
- [ ] Do not add a second rewrite. Pass the proven caller owner to the existing
  `_split_owner_assignment_source` / `_split_owner_assignment_source_with_type`
  implementation so the only emitted candidate is the established synthetic
  owner split.
- [ ] Propagate the resolver's exact reason to `terminal_blocker`; on success,
  attach the proof metadata, source diff/hunks, and materialized label without
  replacing the original attribution.
- [ ] Re-run the focused test command and confirm green.

### Task 3: Protect legacy direct call-return behavior and planner bounds

**Files:**

- Modify: `tools/melee-agent/tests/search/directed/test_window_order_source.py`
- Modify only if required: `tools/melee-agent/src/search/directed/window_order_source.py`

- [ ] Add/retain regression assertions that a direct named call owner still
  materializes without wrapper-copy-chain requirements.
- [ ] Add two fallback leads for the same target chain and assert normal planner
  deduplication plus the global `max_probes` limit prevent duplicate sources.
- [ ] Assert a wrapper rejection does not fall through to a generic source
  guess or a different source-attribution handler.
- [ ] Run the complete directed window-order file:
  `cd tools/melee-agent && pytest tests/search/directed/test_window_order_source.py -q`.

### Task 4: Exercise select-order orchestration with a retained-style fixture

**Files:**

- Modify: `tools/melee-agent/tests/search/test_select_order_search.py` or the
  existing select-order orchestration test file that owns window-order
  continuation fixtures.
- Modify only if required: `tools/melee-agent/src/search/select_order.py`

- [ ] Locate the existing no-compile/fake-compiler fixture used for retained
  window-order probes; do not create a parallel harness.
- [ ] Feed it the reported null-name/null-type attribution and retained-style
  wrapper source.
- [ ] Assert the result manifest contains at most one wrapper-owner source
  variant, exact chain/owner/helper provenance, and either its compiled pcdump
  retention record or its single concrete rejection reason.
- [ ] Run that orchestration test in isolation, first red if a production seam
  is missing, then green after the smallest necessary integration edit.

### Task 5: Focused and broad verification

**Files:** none expected.

- [ ] Run the complete virtual-register/window-order/select-order baseline used
  for this worktree (baseline: 265 passed). Record the exact command and count.
- [ ] Run Ruff on every changed Python file.
- [ ] Run `python -m compileall` on changed production Python packages.
- [ ] Run `git diff --check` and inspect `git diff --stat` plus the full diff for
  accidental broad edits or provenance loss.
- [ ] Confirm `git status --short` contains only the two docs and intended
  source/tests, with no generated artifacts.

### Task 6: Retained-campaign validation outcome and handoff

**Files:** generated output only in a fresh ignored or `/tmp` directory.

- [x] Replayed the retained IG 72 attribution through the branch-local source
  planner in the fresh ignored directory
  `build/select-order/issue1248-inline-owner-replay`, without overwriting the
  original retained campaign.
- [x] Confirmed exactly one bounded source variant,
  `probes/window-order-call-return-ig72-before-0.c`, containing the
  `mnDiagram_CreateFighterHeader(...)` synthetic-owner split for the unique
  `[72, 86, 3]` chain.
- [x] Recorded the first compile blocker: `build/GALE01/report.json` has zero
  `mnDiagram_DrawFighterHeaders` function records, so target lookup cannot
  establish the comparison target.
- [x] Recorded the post-setup `score-source` blocker: the generated
  `probes/window-order-call-return-ig72-before-0.pcdump.txt` contains zero
  occurrences of `mnDiagram_DrawFighterHeaders`, despite the paired source
  containing the target, so no target pcdump or structural-guard score is
  available.
- [ ] Retain compiled pcdump/structural-score evidence after the build-report
  and pcdump target-omission blocker is fixed. Do not repeat compiler setup as
  part of this implementation pass.
- [ ] Present the uncommitted spec, plan, source/test diff, red/green evidence,
  broad test count, lint/compile/diff results, and recorded replay outcome to
  the root agent for review. Do not commit or resolve #1248 before root approval.
