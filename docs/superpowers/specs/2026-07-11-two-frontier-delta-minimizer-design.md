# Two-Frontier Delta Minimizer Design

**Date:** 2026-07-11

**Status:** Approved in brainstorming; awaiting written-spec review

**Scope:** A reusable `melee-agent` command for bounded, closed-world source
recombination between two retained matching frontiers

## 1. Context

`mnDiagram_DrawFighterHeaders` has two complementary source frontiers:

- The approximately 99.84% wrapper-oriented source has the useful compiler
  temporary and ObjObject ordering that improves the row coloring, but it puts
  a compiler-generated row-child home at the wrong stack offset.
- The approximately 99.66% direct source has exact opcode shape, frame size,
  and stack layout, but its natural coloring misses the proven physical
  assignment vector.

The important source difference is narrow. In the observed case, helper
parameter ordering and the corresponding calls change compiler-front-end object
order, backend live ranges, coloring, and stack-home placement. Generic textual
permutation explores a much larger and less relevant space. Existing tooling
can compile and score retained source, combine non-overlapping hunks, parse
COLORGRAPH data, compare compiler passes, inspect ObjObjects, and explain stack
homes, but it does not search the complete closed lattice between exactly two
source frontiers or rank candidates jointly across these four axes.

This design adds that missing bounded search.

## 2. Goals

The feature must:

1. Accept any target function and two full translation-unit source files.
2. Extract AST-anchored, reversible source deltas between the files.
3. Couple edits that must move together to preserve source semantics, such as a
   helper parameter reorder and every corresponding call-argument reorder.
4. Enumerate every legal combination of the observed deltas within an explicit
   candidate budget.
5. Compile every legal candidate and score opcode graph, color graph, ObjObject
   order, and stack homes.
6. Return the exact Pareto frontier when all four evidence lanes complete.
7. Minimize equivalent frontier candidates relative to both input parents.
8. Retain complete source and evidence provenance without modifying repository
   source files.
9. Resume interrupted runs from content-addressed cached artifacts.

## 3. Non-goals

The MVP will not:

- Generate source edits that are absent from both parents.
- Run ordinary statement or expression permutation.
- Use beam search, randomized search, or any other incomplete search strategy.
- Attempt general C semantic equivalence proving.
- Treat a three-axis run as an exact four-axis result.
- Automatically apply a winning candidate to the working tree.
- Require finding a 100% match. A complete, minimized unresolved frontier is a
  valid result.

## 4. Locked design decisions

The brainstorming phase established these decisions:

- The command is reusable, not hard-coded to `mnDiagram_DrawFighterHeaders`.
- Objective donors are inferred automatically and may be overridden. Ambiguous
  inference fails closed.
- The search is closed-world: candidates contain only observed left/right
  deltas.
- Results use an exact Pareto frontier, not a weighted aggregate score.
- ObjObject inspection runs for every locally valid candidate by default.
- The search is exhaustive within its declared budget. It never silently
  truncates the candidate set.
- Source deltas use AST anchors with exact textual replacements rather than a
  full AST pretty-printer.

## 5. Command interface

Add:

```text
melee-agent debug search delta-minimize \
  --function FUNCTION \
  --left LEFT.c \
  --right RIGHT.c \
  [--out-dir DIR] \
  [--max-candidates 64] \
  [--target TARGET.json] \
  [--donor AXIS=left|right]... \
  [--no-objobjects] \
  [--json]
```

`AXIS` accepts `opcode`, `color`, `objobjects`, or `stack-homes`. Overrides are
recorded in objective provenance. `--no-objobjects` is an explicit provisional
mode and cannot emit a four-axis joint solution.

The installed `melee-agent` entrypoint intentionally follows the shared tooling
checkout. Branch-local development and verification therefore use
`cd tools/melee-agent && python -m src.cli ...` until the tooling change reaches
the shared baseline.

## 6. Architecture

The implementation is divided into five independently testable components.

### 6.1 DeltaExtractor

`DeltaExtractor` parses both sources with the repository's tree-sitter C
support. It matches top-level functions and declarations, then anchors changed
text to the smallest supported semantic construct: function signature,
parameter list, declaration, call expression, statement, or expression.

It emits a `DeltaManifest` containing `DeltaAtom` records and constraints.
Formatting-only changes do not become atoms.

### 6.2 ObjectiveProfiler

`ObjectiveProfiler` compiles and profiles both input parents. It derives the
absolute targets and parent donors described in Section 9, records ambiguity,
and creates one immutable `ObjectiveManifest` used for every candidate.

### 6.3 CandidateEnumerator

`CandidateEnumerator` visits every legal atom mask exactly once. It applies
AST-anchored textual replacements to a canonical left source, validates anchor
fingerprints before every replacement, and emits full-unit source candidates.

### 6.4 CandidateEvaluator

`CandidateEvaluator` compiles each source, runs checkdiff and pcdump analysis,
runs the remote inspector, and returns a complete `CandidateProfile`. It reuses
the existing score-source, build-lock, pcdump parser, COLORGRAPH parser,
inspect-output parser, and stack-home/frame-analysis primitives rather than
reimplementing compiler workflows.

### 6.5 ParetoReducer

`ParetoReducer` excludes incomplete profiles from the exact frontier, computes
four-axis dominance, retains every distinct non-dominated vector, minimizes
equivalent masks from both parents, and selects a deterministic `best_next`
representative for human convenience.

## 7. Delta contracts

### 7.1 DeltaAtom

Each atom contains:

```text
atom_id
anchor_kind
anchor_symbol
left_span / right_span
left_text / right_text
left_fingerprint / right_fingerprint
affected_functions
requires[]
incompatible_with[]
semantic_summary
```

Atom IDs are stable hashes of the normalized anchor identity and both textual
forms. Raw byte offsets are evidence, not identity, because an earlier applied
atom may shift later offsets.

### 7.2 Semantic coupling

Primitive changed spans are grouped into one searchable atom when applying
only a subset could silently change behavior while still compiling. Required
coupling includes:

- Function or helper parameter reorder plus corresponding call arguments.
- Helper rename plus declarations, definitions, and calls.
- Declaration/type changes plus mechanically linked initializers or uses when
  the two parent sources demonstrate that relationship.
- A replacement split across adjacent AST nodes whose partial application is
  not source-equivalent to either parent.

The extractor may use dependency edges when two edits remain independently
meaningful but one requires the other. Overlapping replacements that cannot be
normalized become incompatibilities.

When symbol or call-site coupling cannot be resolved uniquely, extraction
stops with `ambiguous-delta-coupling`. The report includes candidate spans and
does not produce speculative hybrids.

The tool assumes the two user-supplied parents are semantically acceptable. It
does not prove their equivalence, but it must not introduce known
signature/call binding errors while recombining them.

## 8. Enumeration and minimization

The left source is the all-zero mask and the right source is the all-one mask.
Dependencies and incompatibilities define the legal masks. A deterministic DFS
enumerates and counts the complete legal set before compilation.

If the legal count exceeds `--max-candidates`, the run stops with
`candidate-budget-exceeded`, reports the exact required count, and writes the
delta manifest. No candidate is compiled and no partial frontier is published.
The MVP has a fixed safety ceiling of 20 coupled atoms. Exceeding it reports
`atom-space-too-large` and requires the user to reduce or regroup the input
delta rather than risking an unbounded preflight. At or below that ceiling, the
reported legal-mask count is exact.

Each materialized candidate records its mask, applied atoms, dependencies,
distance from the left parent, distance from the right parent, source hash, and
compile status.

After Pareto scoring, equivalent objective vectors are minimized in both
directions:

- A left-minimal representative has no proper applied-atom subset with the
  same vector.
- A right-minimal representative has no proper right-to-left reverted-atom
  subset with the same vector.
- Ties use changed-byte count, then stable mask order.

Both directional representatives are retained when they differ. Source size
is not a fifth Pareto objective; it only reduces candidates that already have
the same four-axis vector.

## 9. Objective derivation

The profiler compiles both parents before extracting the final objective
manifest.

### 9.1 Opcode target and donor

The expected object supplies absolute opcode/CFG truth. The parent with the
smaller opcode-graph distance is recorded as the opcode donor. A tie is valid
when both parents have the same distance because the target itself remains
authoritative.

### 9.2 Coloring target and donor

An explicit `--target` is authoritative when supplied. Otherwise the profiler
derives desired physical assignments by aligning expected and current assembly
operands, mapping candidate virtuals through existing role identity, and
cross-checking the result from both parents.

Assignments that resolve from both parents must agree after role anchoring. A
conflict, a reused-role ambiguity, or failure to resolve the required roles
stops with `ambiguous-color-target` and requires an explicit `--target`. Once
the assignment target is unambiguous, the parent with the lower assignment
distance becomes the color donor for secondary graph/order comparison;
`--donor color=...` may override only that secondary donor, not the absolute
assignment target.

### 9.3 ObjObject donor

No front-end ObjObject snapshot exists in the retail binary. ObjObject truth is
therefore explicitly a proxy objective. By default, the color donor also
supplies the ObjObject sequence because this feature is intended to preserve
the front-end ordering responsible for the better coloring. If color evidence
does not choose a unique donor, the profiler stops with
`ambiguous-objobject-donor`. `--donor objobjects=...` resolves it.

### 9.4 Stack-home target and donor

Expected assembly and checkdiff supply absolute frame size and paired stack
references. Existing symbolic/named home analysis maps these references to
stable home identities when possible. The parent with fewer offset/home
mismatches is the stack-home donor.

If an anonymous compiler home cannot be mapped absolutely, the donor's
normalized home/access sequence becomes a labeled proxy for that home only. A
tie with unresolved identities stops with `ambiguous-stack-home-donor` unless
overridden.

### 9.5 Provenance

Every axis records:

```text
reference_kind: absolute | proxy | mixed
reference_artifact
donor: left | right | none
inference_reason
override: true | false
unresolved_roles_or_homes[]
```

A donor override changes a proxy or secondary comparison source; it never
replaces available absolute expected-object truth.

A joint solution may use a proxy ObjObject reference, but the output must state
that zero means “matches the inferred front-end donor,” not “proves retail
front-end identity.”

## 10. Scoring model

All distances are nonnegative and ordered so zero is ideal.

### 10.1 OpcodeGraphDistance

Build normalized assembly control-flow graphs for expected and candidate code.
Basic blocks are nodes containing opcode sequences with register names,
immediates, labels, and relocation spelling removed where checkdiff already
treats them as presentation differences. Directed branch/fallthrough edges
form the graph.

The distance is the ordered tuple:

```text
(changed_opcode_nodes, changed_cfg_edges)
```

Checkdiff structural truth is retained beside this value. A zero tuple must
agree with a structural-match checkdiff result.

### 10.2 ColorGraphDistance

Candidate virtuals are mapped to stable expression/role identities before
comparison. The distance is:

```text
(
  desired_assignment_misses,
  simplify_order_inversions,
  select_order_inversions,
  interference_edge_delta,
  coalesce_delta,
  spill_delta
)
```

The tuple is ordered lexicographically within this axis. Desired physical
assignments are therefore more important than incidental graph similarity.
The existing COLORGRAPH, simplify, select, coalesce, and spill parsers provide
the evidence.

### 10.3 ObjObjectOrderDistance

Add a structured ObjObject-section parser on top of the existing inspector
snapshot slicer. It removes process addresses and derives stable semantic
identities from object kind, source name, type, scope, and normalized
initializer/expression evidence. Scoring is restricted to the target function's
snapshot, which includes relevant inline-expanded helper objects.

The distance is:

```text
(missing_or_extra_objects, order_inversions)
```

Repeated indistinguishable identities that cannot be paired deterministically
produce incomplete evidence rather than arbitrary matching.

### 10.4 StackHomeDistance

Generalize the existing home analysis to include named locals, symbolic homes,
spills, and compiler-temp homes visible through aligned stack accesses. The
distance is:

```text
(
  unresolved_or_mismatched_homes,
  total_absolute_offset_delta,
  home_order_inversions,
  absolute_frame_size_delta
)
```

Home identities and whether each comparison is absolute or proxy remain in the
candidate profile.

## 11. Pareto semantics

Each axis tuple is compared lexicographically. Candidate A dominates candidate
B when A is no worse on all four axis values and strictly better on at least
one. The implementation does not combine axes with weights.

A profile missing any required axis is excluded from the exact frontier. A
completed `--no-objobjects` run publishes a separate provisional three-axis
frontier with `exact_four_axis: false`.

“Exact” means exact for the immutable objective manifest, including any proxy
references explicitly recorded there. It does not claim access to unavailable
retail front-end state.

A four-axis joint solution requires every axis distance to equal its zero
tuple. When no joint solution exists, the run still succeeds with
`status: frontier` and retains the complete non-dominated set.

`best_next` is a presentation convenience, not a replacement for the frontier.
It sorts frontier candidates by joint-zero axis count, then the four axis
tuples in fixed `opcode`, `color`, `objobjects`, `stack-homes` order, then
minimized parent distance, changed bytes, and stable candidate ID.

## 12. Execution and caching

The command runs these resumable phases:

1. Validate sources, target function, compiler context, and expected object.
2. Compile/profile both parents and write `objective-manifest.json`.
3. Extract, couple, and validate deltas in `delta-manifest.json`.
4. Count and enumerate every legal mask.
5. Compile every candidate and collect checkdiff/pcdump evidence.
6. Inspect every locally valid candidate for ObjObjects.
7. Compute and minimize the Pareto frontier.

Candidate source and evidence are content-addressed. A cache key includes:

- Full source hash.
- Function and cflags/build-unit identity.
- Compiler identity.
- Expected object hash.
- Objective-manifest hash.
- Scorer/parser schema versions.
- Inspector version and invocation mode.

The existing repository build lock protects build-tree operations. Candidate
sources live only below `--out-dir`; the command never patches the working-tree
source. Ledger and summary files use atomic replacement so interruption cannot
publish a partially written result.

Reruns validate provenance, reuse complete artifacts, invalidate stale entries,
and resume the first incomplete phase.

## 13. Failures and result status

Candidate-local failures are evidence, not fatal run errors:

- Syntax or compiler rejection.
- An invalid materialized anchor.
- Target function absent from candidate output.
- Candidate-specific pcdump failure with compiler diagnostics.

They remain in the ledger and are excluded from scoring.

Run-level failures stop exact publication:

- Invalid inputs or missing expected object.
- Ambiguous donor, target, or semantic coupling.
- Candidate-budget or atom-space overflow.
- Inspector unavailability or timeout.
- Infrastructure pcdump/build failure.
- Corrupt or contradictory cached evidence.

An interrupted or infrastructure-failed run writes `status: incomplete`, keeps
resumable artifacts, and does not write an exact frontier. The human report
contains the next command or override needed to continue.

Completed statuses are:

- `matched`: at least one joint-zero candidate.
- `frontier`: exact evaluation completed without a joint-zero candidate.
- `provisional`: explicitly requested incomplete-axis evaluation completed.
- `incomplete`: exact evaluation did not finish.

## 14. Output contract

The primary `result.json` contains:

```text
schema_version
status
exact_four_axis
function
inputs
compiler_provenance
objective_manifest
delta_manifest
candidate_budget
candidate_counts
candidates[]
pareto.candidate_ids[]
pareto.objective_vectors[]
pareto.minimal_from_left[]
pareto.minimal_from_right[]
best_next
joint_solutions[]
cache_stats
blockers[]
```

Every candidate row links retained source, mask, atoms, parent distances,
compile/checkdiff result, pcdump, inspector snapshot, four objective distances,
dominators, and failure details. The text renderer summarizes the donors,
delta lattice, candidate counts, frontier vectors, minimized edits, and next
action without hiding the JSON evidence.

## 15. Testing

### 15.1 Unit tests

Cover:

- AST anchoring and formatting-only suppression.
- Signature/call coupling for same-typed reordered parameters.
- Rename, declaration/use, dependency, incompatibility, and ambiguity cases.
- Exact legal-mask counting and budget preflight.
- Deterministic materialization and anchor-fingerprint rejection.
- Donor inference, ties, conflicts, overrides, and proxy provenance.
- Opcode CFG normalization and structural-zero cross-checking.
- Role-anchored color tuple construction.
- ObjObject normalization, repeated-identity ambiguity, and order distance.
- Named, symbolic, spill, and compiler-temp stack-home distance.
- Four-axis dominance, incomplete evidence, and deterministic `best_next`.
- Bidirectional minimization of equivalent masks.
- Cache-key stability, stale evidence, atomic resume, and corruption handling.

### 15.2 Integration tests

Add a compact wrapper/direct C fixture modeled on
`mnDiagram_DrawFighterHeaders`. One parent wins coloring and ObjObject order;
the other wins stack homes while preserving opcode shape. A deterministic fake
compiler/inspector proves that:

- Every legal mask is evaluated once.
- Compile-invalid masks remain visible but never enter the frontier.
- All valid masks receive all four metrics.
- The exact Pareto frontier is reproducible.
- Equivalent winners are minimized from both parents.
- Interrupted evaluation resumes without repeating valid cached work.

Hermetic checkdiff, pcdump, and inspector snapshots exercise the production
parsers. CLI tests cover help/golden output, JSON schema, ambiguity diagnostics,
budget overflow, provisional mode, and interrupted infrastructure.

### 15.3 Real-case acceptance

Run the command on the retained approximately 99.84% wrapper source and 99.66%
direct source for `mnDiagram_DrawFighterHeaders`. Acceptance requires:

- A complete four-axis profile for both parents and every valid hybrid.
- Exact enumeration within the declared budget.
- Retained sources and evidence for every Pareto candidate.
- Reproducible minimized masks from both parents.
- A joint solution if one exists, otherwise a proven minimal unresolved
  frontier.

Existing combine, score-source, directed-search, parser, and artifact-lifecycle
tests must continue to pass.

## 16. Implementation boundary

The feature belongs in focused modules under `tools/melee-agent/src/search/`
with thin CLI wiring under the existing debug-search application. It should add
small reusable parser/profile helpers under `mwcc_debug` only where existing
parsers lack structured ObjObject or generalized stack-home contracts.

It must reuse existing compilation, score-source, source-patch, build-lock,
COLORGRAPH, inspect-diff, and artifact lifecycle facilities. Unrelated search
or decompilation refactors are outside scope.
