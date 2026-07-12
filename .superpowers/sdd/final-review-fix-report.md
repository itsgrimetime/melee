# Final Review Fix Report

## Outcome

All four final-review findings are fixed and committed. Exact allocator namespace
reuse is now proved pairwise from complete early IR semantics, real inspector
duplicates no longer use measured order as identity, every rerun invalidates
previous publications before completion preflight, and ambiguity recovery text
requests a versioned target with explicit v2 reviewed bindings. The gates remain
fail-closed: incomplete or ambiguous identity does not publish an exact result.

The retained real run completed all eight legal candidates and published a clean
Pareto frontier with no blockers. The retained family has no exact joint solution;
no candidate was guessed or promoted to exact.

## Finding 1: full-range allocator namespace identity

### Diagnosis

The original structural witness described only allocator decisions but promoted
the entire raw virtual range. A non-decision or coalesced virtual could therefore
change meaning without changing the witness. Extending that late-pass witness was
also insufficient on the retained parents: each parent reported 110 graph nodes,
but late semantic facts covered only 60 nodes (58 usable after two truncated
records), leaving 50 missing and 20 duplicate semantic classes containing 40
members.

The replacement solver uses the exact `BEFORE GLOBAL OPTIMIZATION` IR from both
parents. It treats 0..31 as the ABI register domain and proves a bijection for
every true virtual 32..n-1. It jointly refines paired CFG blocks, normalized
instruction skeletons, register occurrence positions, first-def/use multisets,
dependency edges, and already-proved canonical roles. Physical ABI operands keep
their identities; virtual operands do not inherit raw numbers. Relocations are
normalized only when doing so is unambiguous within the block and operand role.
Reviewed v2 bindings are checked as injective seeds and against the same semantic
constraints.

The solver deliberately excludes assigned physical registers, live ranges,
spills, interference, coloring decisions, simplify/coalesce state, and all other
allocator outcomes. It returns `None` for missing early-IR nodes, CFG mismatch,
ambiguous residual classes, conflicting reviewed anchors, incomplete coverage, or
a non-bijective result. ABI registers are mapped separately and are never confused
with the virtual namespace. All exact mapping call sites now use this pairwise
proof; witness-equality shortcuts were removed. The namespace epoch is
`delta-minimize-role-namespace.v4`, and the parser schema epoch includes
`color.v4`.

### TDD evidence

The initial RED changed a coalesced/non-decision virtual's normalized first-def
while preserving the old decision/traversal/coalesce witness; the old witness
remained equal. A second RED changed a non-decision use operand and again left the
old witness equal. Focused GREEN regressions are:

```text
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_evaluator.py::test_structural_namespace_witness_covers_coalesced_virtual_identity \
  tests/search/delta_minimize/test_evaluator.py::test_structural_namespace_witness_covers_nondecision_use_operands
2 passed
```

Review of that first implementation exposed the retained late-pass coverage gap,
so the final pairwise early-IR API was introduced test-first. Before the API and
call-site implementation, these regressions failed because late facts returned no
complete identity, early semantic changes were unobserved, and there was no way
to prove a non-raw-number bijection. They now pass:

```text
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_evaluator.py::test_early_ir_identity_covers_virtuals_missing_from_late_pass \
  tests/search/delta_minimize/test_evaluator.py::test_early_ir_semantic_change_changes_full_identity \
  tests/search/delta_minimize/test_evaluator.py::test_early_ir_occurrences_prove_nonidentity_namespace_bijection \
  tests/search/delta_minimize/test_evaluator.py::test_pairwise_namespace_rejects_conflicting_reviewed_anchor \
  tests/search/delta_minimize/test_evaluator.py::test_pairwise_namespace_rejects_missing_early_ir_virtual \
  tests/search/delta_minimize/test_evaluator.py::test_pairwise_namespace_excludes_late_allocator_objective_state
6 passed
```

The nonidentity regression swaps virtuals 47 and 54 and proves the semantic
bijection rather than relying on raw-number equality. Existing exact-namespace,
semantic-reanchor, objective inference, v2 reviewed-binding, and integration
fixtures were updated to provide complete early IR rather than weakening the
gate.

## Finding 2: ObjObject duplicate occurrence identity

### TDD evidence and fix

The RED real-inspector-format fixture demonstrated that two duplicate ObjObjects
were reported complete with occurrences `("0", "1")`, because measured appearance
order had been used as pairing identity:

```text
python -m pytest --no-cov -q \
  tests/test_objobject_profile.py::test_real_inspector_duplicate_order_is_not_occurrence_identity
1 failed
```

The parser no longer creates occurrence identity from `order`. It accepts an
independent inspector/source occurrence anchor when one is present; otherwise a
duplicate identity remains unresolved and the comparison fails closed. GREEN:

```text
python -m pytest --no-cov -q \
  tests/test_objobject_profile.py::test_real_inspector_duplicate_order_is_not_occurrence_identity \
  tests/test_objobject_profile.py::test_occurrence_evidence_disambiguates_duplicate_order
2 passed
```

Unique objects and fixtures with explicit stable occurrence evidence remain
complete. The ObjObject/parser epoch is `objobjects.v2`.

## Finding 3: stale publications after a lower-budget rerun

### TDD evidence and fix

The RED regression first completed a run, then reran the same output directory
with a smaller `max_candidates`. The expected budget failure left the previous
exact `result.json` and `candidates.json` visible:

```text
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_run.py::test_lower_candidate_budget_removes_stale_exact_publications
1 failed
```

`run_delta_minimize()` now invalidates current publications unconditionally at
run entry, before budget, target, donor, or objective preflight. Compatible
content-addressed parent and candidate evidence remains reusable. Inputs that
affect completion (`include_objobjects`, target, donor overrides, and budget)
therefore cannot leave an earlier publication advertised as current. GREEN:

```text
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_run.py::test_lower_candidate_budget_removes_stale_exact_publications \
  tests/search/delta_minimize/test_run.py::test_extractor_schema_upgrade_removes_stale_publications_before_enumeration \
  tests/search/delta_minimize/test_run.py::test_objective_context_change_removes_stale_publications_before_ambiguity
3 passed
```

The regression also confirms compatible evidence-cache entries survive the
failed rerun.

## Finding 4: versioned ambiguity recovery text

The RED golden assertion showed recovery text named only a v1 target. The text
now requests a versioned color target and tells users that cross-parent role
ambiguity requires v2 reviewed `parent_role_bindings`:

```text
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_cli.py::test_text_renderer_requests_versioned_target_for_role_ambiguity
1 passed
```

## Retained real acceptance

The exact frozen Task 3 command was rerun from
`/Users/mike/.codex/worktrees/eeff/melee`, loading this branch through
`PYTHONPATH` and using:

```text
function: mnDiagram_DrawFighterHeaders
left:  /Users/mike/.codex/worktrees/828b/melee/build/delta-minimize/fighter-wrapper.c
right: /Users/mike/.codex/worktrees/eeff/melee/build/delta-minimize/fighter-direct.c
target: /Users/mike/code/melee/.claude/worktrees/codex-delta-cross-parent-role-map/build/delta-minimize/issue-1238-real-v2/target.yaml
donors: color=left, stack-homes=right
budget: 64
output: /Users/mike/.codex/worktrees/eeff/melee/build/delta-minimize/fighter-real-v2-task3
```

Frozen hashes were preserved:

```text
left source:  0f38bf2740123c3bbf6b9c18ad10123cc0db3f6e14bd5041057d49921eaec7e2
right source: e7f3a66ab56c14b8841591ade19425c4cb45df614795ef15e4d9fa983967af96
left pcdump:  db41d64051334cace6e38b2db91ade6d6addfff0a4ab06b689b5cc1384578333
right pcdump: 433e4954aa3b4402dedb61ef9830ac6aa03a393b1147217654f62e0350196598
```

Direct proof over the captured v4 parents covered all 110 nodes, including all
78 true virtuals, and produced a full bijection without assuming raw equality.
The reviewed roles 64 and 78 were honored. The objective manifest records
`delta-minimize-role-namespace.v4` and the strict v2 source/pcdump bindings.

The first attempt reached candidate evaluation but stopped incomplete when the
external inspector failed on `mask-100`. The exact retry reused the compatible
parents; `mask-100` succeeded, then all remaining candidates completed. Final
result:

```text
exit: 0
status: frontier
blockers: []
candidate counts: legal=8, viable=8, complete=8
cache entries: parents=2, candidates=8
Pareto candidates: mask-000, mask-001, mask-010, mask-011
exact-match candidates: []
joint solutions: []
```

This is a successful retained acceptance of the proof and publication path. It
is not an exact match because the retained candidate family contains no joint
zero solution; the tool correctly publishes the complete frontier without
inventing one.

## Final verification

All commands were rerun on current HEAD after the final solver commit:

```text
cd tools/melee-agent
python -m pytest --no-cov -q tests/search/delta_minimize \
  tests/test_objobject_profile.py tests/test_colorgraph_profile.py
586 passed in 7.53s

python -m ruff check src/search/delta_minimize \
  src/mwcc_debug/objobject_profile.py tests/search/delta_minimize \
  tests/test_objobject_profile.py
All checks passed!

cd ../..
python configure.py && ninja
Succeeded: REPORT and PROGRESS targets completed.

git diff --check
Passed with no output.
```

## Commits

```text
6fcb1dfd9 fix: require full allocator namespace identity
ece9be1f3 fix: reject ordered ObjObject duplicate identity
593b8e943 fix: invalidate delta publications before rerun
69bc696f4 fix: clarify versioned color target recovery
0a9313cfb test: bind exact namespace fixtures to full identity
ff9b4aaa5 fix: anchor allocator namespaces to semantic uses
f3be3721a fix: prove allocator namespaces pairwise from early IR
```

## Files and self-review

Production changes are limited to:

- `tools/melee-agent/src/mwcc_debug/role_descriptor.py`
- `tools/melee-agent/src/mwcc_debug/objobject_profile.py`
- `tools/melee-agent/src/search/delta_minimize/evaluator.py`
- `tools/melee-agent/src/search/delta_minimize/objectives.py`
- `tools/melee-agent/src/search/delta_minimize/render.py`
- `tools/melee-agent/src/search/delta_minimize/run.py`

Regressions are in the corresponding delta-minimize evaluator, objectives,
integration, run, CLI, and ObjObject test modules.

Self-review specifically rechecked that exact maps cannot be constructed from
raw virtual-number equality, allocator outcomes, measured ObjObject order, or an
incomplete early-IR domain; reviewed anchors constrain rather than override the
proof. Publication invalidation happens before all completion-changing preflight
paths while evidence caches remain content-addressed. The tracked worktree is
clean. The requested report and supplied review artifacts remain untracked by
design.

One non-blocking repository baseline remains: running Ruff directly on the full
legacy `src/mwcc_debug/role_descriptor.py` reports seven pre-existing style
items (import sorting and legacy annotation forms). The mandated Ruff scope does
not include that file and is clean; the final change did not expand those legacy
categories.
