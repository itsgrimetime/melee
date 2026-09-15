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
- ObjObject inspection runs for every successfully compiled, viable candidate
  by default.
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
  [--namespace-review REVIEW.yaml] \
  [--donor AXIS=left|right]... \
  [--no-objobjects] \
  [--json]
```

`AXIS` accepts `color`, `objobjects`, or `stack-homes`. Opcode scoring always
uses the expected object, so an opcode donor override would have no behavioral
meaning and is not supported. Overrides are recorded in objective provenance.
`--no-objobjects` is an explicit provisional mode and cannot emit a four-axis
joint solution.

`--namespace-review` is valid only with a
`delta-minimize-color-target.v2` target. Omitting the sidecar in that context
starts reviewed-namespace discovery; supplying it resumes the same run after
the request has been inspected and sealed. V1 targets never accept a reviewed
namespace sidecar.

`--target` accepts `delta-minimize-color-target.v1`, a versioned validation of
the force-physical target already consumed by `debug target score-source`:

```text
schema_version: delta-minimize-color-target.v1
function: FUNCTION
class_id: INTEGER
baseline_dump: PATH
force_phys: { IG_INDEX: PHYSICAL_REGISTER, ... }
coalesce_preservation: BOOLEAN
```

The baseline dump supplies the role descriptors used to reanchor its IG-indexed
mapping into each candidate. The command validates schema version, function,
class, dump availability, IG uniqueness/resolution, physical-register values,
and coalesce policy before profiling. It does not accept
`role_descriptor.TargetSpec` JSON directly.

V1 remains the automatic semantic-reanchor format. When two parents contain
descriptor-identical roles, operators may instead supply reviewed cross-parent
bindings with `delta-minimize-color-target.v2`:

```yaml
schema_version: delta-minimize-color-target.v2
function: mnDiagram_DrawFighterHeaders
class_id: 0
baseline_side: left
baseline_dump: /absolute/path/to/left.pcdump
force_phys:
  64: 30
  78: 29
coalesce_preservation: false
parent_role_bindings:
  left:
    source_sha256: 0f38bf2740123c3bbf6b9c18ad10123cc0db3f6e14bd5041057d49921eaec7e2
    pcdump_sha256: db41d64051334cace6e38b2db91ade6d6addfff0a4ab06b689b5cc1384578333
    canonical_to_parent:
      64: 64
      78: 78
  right:
    source_sha256: e7f3a66ab56c14b8841591ade19425c4cb45df614795ef15e4d9fa983967af96
    pcdump_sha256: 433e4954aa3b4402dedb61ef9830ac6aa03a393b1147217654f62e0350196598
    canonical_to_parent:
      64: 64
      78: 78
```

The map direction is canonical baseline IG to raw parent IG. V2 requires exact
top-level and nested fields, both parent sides, lowercase 64-character SHA-256
values, total and injective maps whose keys exactly equal `force_phys`, and an
identity map on the baseline side. The baseline dump and both retained parent
source/pcdump byte hashes must match. Every selected role must exist in the
declared class and be a minimum-cost semantic match; review may choose among
tied minima but cannot select an unrelated role.

A candidate consumes a reviewed map only when its exact source and pcdump bytes
match that parent, or when its versioned structural namespace witness exactly
matches a reviewed parent. Otherwise ordinary semantic reanchoring applies.
Ambiguous or incomplete mappings leave the viable candidate incomplete, and
any such viable candidate prevents exact frontier publication. Raw IG equality
alone is never identity evidence, and malformed v2 evidence never falls back to
v1 interpretation.

The installed `melee-agent` entrypoint intentionally follows the shared tooling
checkout. Branch-local development and verification therefore use
`cd tools/melee-agent && python -m src.cli ...` until the tooling change reaches
the shared baseline.

### 5.1 Reviewed namespace discovery and sealing

The normative reviewed-authority schemas and proof rules are defined by
[`2026-07-11-issue-1238-cross-parent-role-bindings-design.md`](2026-07-11-issue-1238-cross-parent-role-bindings-design.md)
and
[`2026-07-11-issue-1238-reviewed-namespace-sidecar-design.md`](2026-07-11-issue-1238-reviewed-namespace-sidecar-design.md).
Those companion specifications define automatic v5 structural witnesses,
request and sealed-review schemas, exact-content inheritance, and resolution
precedence. This specification adopts those definitions rather than treating
raw IG equality as evidence.

`--namespace-review PATH` accepts a sealed, provenance-bound namespace sidecar.
When automatic v5 proof cannot resolve every viable allocator namespace, the
first `delta-minimize` run captures the complete raw lattice, exits incomplete,
and writes `namespace-review-request.yaml`. The text and JSON results name both
that request path and every unresolved artifact ID under
`inputs.namespace_review_request` and `inputs.namespace_review_unresolved`.
No objective manifest,
candidate profile publication, or Pareto frontier is published at this stage.

The operator workflow is deliberately explicit:

```text
# Discover and capture all raw evidence.
melee-agent debug search delta-minimize ... --out-dir RUN

# Inspect RUN/namespace-review-request.yaml, including content hashes,
# automatic diagnostics, reviewed anchors, and unresolved artifact IDs.

# Seal one authority choice for every unresolved exact-content group.
melee-agent debug search delta-namespace-review seal \
  --request RUN/namespace-review-request.yaml \
  --accept-identity parent:right \
  --map candidate:mask-100=mask-100-map.yaml \
  --out RUN/reviewed-namespaces.yaml

# Rerun without recapturing compatible raw evidence.
melee-agent debug search delta-minimize ... --out-dir RUN \
  --namespace-review RUN/reviewed-namespaces.yaml
```

Sealing is explicit review authority, not an automatic fallback. Identity
approvals are expanded to every canonical/artifact pair in the namespace, and
map approvals must already contain the complete bijection. The sealed sidecar
contains no identity shorthand. Exact source-plus-pcdump aliases share one
approval and inherit it on rerun; approving an alias separately is redundant.
An automatic v5 proof cannot be overridden by the sidecar.

## 6. Architecture

The implementation is divided into five independently testable components.

### 6.1 DeltaExtractor

`DeltaExtractor` parses both sources with the repository's tree-sitter C
support. It matches top-level functions and declarations, then anchors changed
text to the smallest supported semantic construct: function signature,
parameter list, declaration, call expression, statement, or expression.

It emits a `DeltaManifest` containing `DeltaAtom` records and dependency
constraints. Standalone formatting-only changes are aggregated into at most one
`presentation-only` atom. This preserves exact endpoint reproduction without
turning whitespace into an ordinary permutation search.

### 6.2 ObjectiveProfiler

`ObjectiveProfiler` compiles and profiles both input parents. It derives the
absolute targets and parent donors described in Section 9, records ambiguity,
and creates one immutable `ObjectiveManifest` used for every candidate. For a
v2 reviewed-namespace run, objective publication is deferred until the raw
lattice has been captured and every viable namespace is resolved. Parent
capture remains the only profiler work performed before discovery.

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

`ParetoReducer` computes four-axis dominance only after the evaluator proves
completeness for every viable mask. Any viable incomplete profile blocks exact
publication rather than being omitted. Once complete, the reducer retains every
non-dominated mask, groups equivalent vectors, minimizes equivalent masks from
both parents, and selects a deterministic `best_next` representative for human
convenience.

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
meaningful but one requires the other. Binary atoms are never mutually
incompatible: the all-right mask must remain legal. Overlapping replacements
must be merged into one composite atom; an overlap that cannot be merged stops
extraction with `unmergeable-overlapping-delta`. Dependency cycles are collapsed
into one composite atom before enumeration.

When symbol or call-site coupling cannot be resolved uniquely, extraction
stops with `ambiguous-delta-coupling` and does not produce speculative hybrids.
Because this happens before a delta manifest or lattice exists, it is not a
namespace-review case. The run writes only
`delta-coupling-diagnostic.json` (`delta-coupling-diagnostic.v1`) alongside the
retained parent evidence. The diagnostic is bound to the function and exact
left/right source hashes and preserves the extraction context plus deterministic
competing pairing choices or explicit conflicting evidence groups, atom IDs,
symbols, and left/right spans. These groups are derived from the ambiguous
binding path itself; unrelated nearby primitive atoms are never presented as
choices. The diagnostic explicitly records that semantic-coupling review is
unsupported and directs the user to edit either parent and rerun. Human output
summarizes those alternatives/evidence groups; `--json` returns a structured
`delta-minimize-error.v1` envelope. Any manifest from a reused output directory
is invalidated, and no delta manifest, candidates, result, or namespace-review
request is published for the ambiguous run.

The tool assumes the two user-supplied parents are semantically acceptable. It
does not prove their equivalence, but it must not introduce known
signature/call binding errors while recombining them.

### 7.3 Supported semantic-binding subset

The MVP safely couples only bindings that can be resolved within one parsed
translation unit: top-level function definitions/declarations and direct calls
whose callee is an unshadowed identifier. It supports parameter reorders,
renames, and corresponding direct call arguments in that subset.

Changed bindings are unsupported when they depend on macro-generated calls or
definitions, changed conditional-compilation branches, indirect/function-pointer
calls, ambiguous shadowing, K&R declarations, or unresolved external call
sites. The extractor detects these shapes conservatively and stops with
`unsupported-semantic-binding`; it does not infer bindings from tree-sitter
syntax alone. Unchanged macro use outside affected bindings remains allowed.

## 8. Enumeration and minimization

The left source is the all-zero mask and the right source is the all-one mask.
Dependencies define the legal masks. Extraction must prove both endpoint masks
legal and materialize them byte-for-byte equal to their respective input files.
Failure is `endpoint-reproduction-failed`, a run-level extractor invariant.
A deterministic DFS enumerates and counts the complete legal set before
compilation.

If the legal count exceeds `--max-candidates`, the run stops with
`candidate-budget-exceeded`, reports the exact required count, and writes the
delta manifest. No candidate is compiled and no partial frontier is published.
The MVP has a fixed safety ceiling of 20 coupled atoms. Exceeding it reports
`atom-space-too-large` and requires the user to reduce or regroup the input
delta rather than risking an unbounded preflight. At or below that ceiling, the
reported legal-mask count is exact.

Each materialized candidate records its mask, applied atoms, dependencies,
distance from the left parent (`popcount(mask)`), distance from the right parent
(`atom_count - popcount(mask)`), source hash, and compile status.

After Pareto scoring, equivalent objective vectors are minimized in both
directions:

- `minimal_from_left` contains the single argmin of
  `(popcount(mask), changed_bytes_from_left, mask, candidate_id)`.
- `minimal_from_right` contains the single argmin of
  `(atom_count - popcount(mask), changed_bytes_from_right, mask,
  candidate_id)`.
- The deterministic group `representative` is the single argmin of
  `(min(popcount(mask), atom_count - popcount(mask)),
  min(changed_bytes_from_left, changed_bytes_from_right), mask,
  candidate_id)`.

Both directional representatives are retained when they differ. Source size
is not a fifth Pareto objective; `changed_bytes_from_left` and
`changed_bytes_from_right` count unequal bytes against the named parent,
including length differences, and only break ties among candidates that
already have the same four-axis vector.

The raw frontier remains separate from these minimized views:

- `pareto.candidate_ids` contains every complete, viable, non-dominated mask.
- Each objective-vector group lists all masks producing that vector.
- `minimal_from_left` and `minimal_from_right` are directional subsets of each
  group.
- The deterministic representative is metadata on the group, not a deletion
  from the raw frontier.
- `joint_solutions` is the union of left- and right-minimal candidates in every
  joint-zero group; `joint_zero_all_candidate_ids` preserves the unminimized
  membership.

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

An explicit v2 target may resolve a tied cross-parent role only through its
reviewed, byte-bound parent mappings. Hybrids inherit a mapping only from an
exactly equal versioned structural namespace witness; otherwise they follow the
same semantic-reanchor path as v1 and fail closed on ambiguity.

Simplify order, select order, interference edges, coalesce mappings, and spill
state have no binary-side absolute reference. Each compares against the selected
color donor's pcdump profile after role reanchoring. If parent assignment
distances tie, the secondary profiles may choose no donor only when they are
identical. A tie with different secondary profiles stops with
`ambiguous-color-donor` and requires `--donor color=left|right`.

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
The assignment component compares to the absolute force-physical target. Every
remaining component compares to the role-reanchored color-donor pcdump recorded
in the objective manifest. The existing COLORGRAPH, simplify, select, coalesce,
and spill parsers provide the evidence.

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
produce incomplete evidence rather than arbitrary matching. Because the
candidate remains viable, that incomplete evidence makes the whole exact run
`incomplete` until resolved.

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

Exact publication requires every legal mask to end in exactly one of two
states: compiler-rejected with concrete diagnostics, or viable and complete on
every required axis. A viable profile missing any required metric could
dominate the visible candidates, so it makes the entire run `incomplete`; it is
never silently excluded. A completed `--no-objobjects` run publishes a separate
provisional three-axis frontier with `exact_four_axis: false`.
The same all-viable-candidates completeness requirement applies to the three
requested axes in provisional mode.

“Exact” means exact for the immutable objective manifest, including any proxy
references explicitly recorded there. It does not claim access to unavailable
retail front-end state.

A four-axis joint solution requires every axis distance to equal its zero
tuple. Completed-status precedence is `matched`, then `joint-zero`, then
`frontier`: any candidate passing the repository's exact object/checkdiff gate
produces `matched` regardless of proxy-axis distance; otherwise an all-zero
objective vector produces `joint-zero`; otherwise the exact non-dominated set
produces `frontier`. Exact-match candidates are always retained separately even
if a proxy objective would keep them off the Pareto frontier. If an opcode zero
tuple disagrees with checkdiff structural truth, the evidence is contradictory
and the run becomes `incomplete` rather than reporting any completed status.

`best_next` is a presentation convenience, not a replacement for the frontier.
It is the ascending lexicographic argmin of
`(not exact_object_match, -zero_axis_count, opcode, color, objobjects,
stack_homes, min_parent_atom_distance, min_changed_bytes, candidate_id)` over
the union of frontier and exact-match candidates. Thus exact matches sort
first, then candidates with more zero axes; axis tuples retain the fixed
`opcode`, `color`, `objobjects`, `stack-homes` order.

## 12. Execution and caching

The ordinary v1 command runs these resumable phases:

1. Validate sources, target function, compiler context, and expected object.
2. Compile/profile both parents and write `objective-manifest.json`.
3. Extract, couple, and validate deltas in `delta-manifest.json`.
4. Count and enumerate every legal mask.
5. Compile every candidate and collect checkdiff/pcdump evidence.
6. Inspect every successfully compiled, viable candidate for ObjObjects.
7. Compute and minimize the Pareto frontier.

A v2 reviewed-namespace run has a separate discovery/resume order:

1. Validate inputs and capture both parents.
2. Extract deltas, count the exact legal set, and enumerate every mask.
3. Compile/checkdiff/pcdump/inspect every candidate into the raw evidence
   ledger.
4. Resolve automatic v5 and exact-content-inherited namespaces.
5. If any viable exact-content group remains unresolved, write
   `namespace-review-request.yaml`, publish only an `incomplete` result, and
   stop without an objective manifest or derived candidate profiles.
6. On a sealed rerun, validate the sidecar against the request and resolve all
   namespaces without recapturing compatible raw evidence.
7. Publish the objective manifest, derive candidate profiles, and compute and
   minimize the exact frontier.

Candidate source and evidence are content-addressed in two layers. The raw
capture key includes:

- Full source hash.
- Function and cflags/build-unit identity.
- Compiler identity.
- Expected object hash.
- A raw-capture epoch binding the target bytes, delta-manifest hash, parser and
  evidence schemas, inspector version/mode, and ObjObject setting.
- Scorer/parser schema versions.
- Inspector version and invocation mode.

Raw inspection reuse requires the exact full-source hash; token equivalence is
not sufficient because preprocessing constructs such as `__LINE__`,
`__FILE__`, and `#line` can make byte- or position-different sources compile
differently. Derived objective distances and profiles are separately bound to
the immutable objective-manifest hash and resolved namespace provenance. Thus
discovery can cache raw artifacts before an objective exists, while a reviewed
rerun can reuse those artifacts without allowing stale derived scores.

The existing repository build lock protects build-tree operations. Candidate
sources live only below `--out-dir`; the command never patches the working-tree
source. Ledger and summary files use atomic replacement so interruption cannot
publish a partially written result.

Reruns validate provenance, reuse complete artifacts, invalidate stale entries,
and resume the first incomplete phase.

## 13. Failures and result status

Candidate-local failures are evidence, not fatal run errors:

- Syntax or compiler rejection.
- Pcdump absence caused directly by that recorded compiler rejection.

They remain in the ledger and are excluded from scoring.

Run-level failures stop exact publication:

- Invalid inputs or missing expected object.
- Ambiguous donor, target, or semantic coupling.
- Candidate-budget or atom-space overflow.
- Invalid materialized anchors or endpoint-reproduction failure.
- A successfully compiled candidate whose target function is absent from the
  pcdump or whose required metric cannot be produced.
- Inspector unavailability or timeout.
- Infrastructure pcdump/build failure.
- Corrupt or contradictory cached evidence.

An interrupted or infrastructure-failed run writes `status: incomplete`, keeps
resumable artifacts, and does not write an exact frontier. The human report
contains the next command or override needed to continue.

Completed statuses are:

- `matched`: at least one exact object/checkdiff match.
- `joint-zero`: every declared objective is zero, but exact object equality was
  not established. Proxy references remain prominently labeled but do not
  prevent `matched` when the independent exact-object gate passes.
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
pareto.groups[].objective_vector
pareto.groups[].candidate_ids[]
pareto.groups[].minimal_from_left[]
pareto.groups[].minimal_from_right[]
pareto.groups[].representative
pareto.exact_match_candidate_ids[]
pareto.joint_solutions[]
pareto.joint_zero_all_candidate_ids[]
best_next
cache_stats
blockers[]
```

For a completed or provisional result, every candidate row links retained
source, mask, atoms, parent distances, compile/checkdiff result, pcdump,
inspector snapshot, objective distances, dominators, and failure details. The
text renderer summarizes the donors, delta lattice, candidate counts, frontier
vectors, minimized edits, and next action without hiding the JSON evidence.

A v2 discovery-stage `incomplete` result uses the same top-level schema with
`exact_four_axis: false`, `objective_manifest: {}`, `pareto: null`,
`best_next: null`, and `candidate_counts.complete: 0`. Each `candidates[]` row
is raw-only and contains `candidate_id`, `mask`, `source_hash`, `source_path`,
and `evidence`; it does not contain objective distances or dominators.
`blockers` contains `namespace-review-required`, while
`inputs.namespace_review_request` and `inputs.namespace_review_unresolved`
identify the sealing work required to continue.

## 15. Testing

### 15.1 Unit tests

Cover:

- AST anchoring and aggregation of standalone formatting into one presentation
  atom.
- Signature/call coupling for same-typed reordered parameters.
- Rename, declaration/use, dependency, overlap merge, and ambiguity cases.
- Unsupported macro-generated, indirect, shadowed, and preprocessor-dependent
  bindings fail closed.
- Exact legal-mask counting and budget preflight.
- Deterministic materialization, byte-exact legal endpoints, and
  anchor-fingerprint rejection as a run invariant.
- Donor inference, ties, conflicts, overrides, and proxy provenance.
- Versioned target-schema validation and role reanchoring from its baseline
  dump.
- Opcode CFG normalization and structural-zero cross-checking.
- Role-anchored color tuple construction.
- ObjObject normalization, repeated-identity ambiguity, and order distance.
- Named, symbolic, spill, and compiler-temp stack-home distance.
- Four-axis dominance, incomplete evidence, and deterministic `best_next`.
- Any viable incomplete candidate prevents exact frontier publication.
- Completed-status precedence for exact matches, joint-zero vectors, and
  ordinary frontiers, including an exact match that differs from a proxy donor.
- Bidirectional minimization of equivalent masks.
- Cache-key stability, stale evidence, atomic resume, and corruption handling.
- Exact-source inspection reuse, including a negative token-equivalent
  `__LINE__` case.
- Automatic v5 namespace proof, `reviewed-namespaces.v1` sidecar resolution,
  exact-content inheritance, and the prohibition on overriding automatic
  proof.
- Strict request/sidecar schemas, complete expanded bindings, provenance
  binding, and rejection of stale or partial review authority.

### 15.2 Integration tests

Add a compact wrapper/direct C fixture modeled on
`mnDiagram_DrawFighterHeaders`. One parent wins coloring and ObjObject order;
the other wins stack homes while preserving opcode shape. A deterministic fake
compiler/inspector proves that:

- Every legal mask is evaluated once.
- The all-zero and all-one masks are legal and reproduce the input files
  byte-for-byte.
- Compile-invalid masks remain visible but never enter the frontier.
- Every successfully compiled, viable mask receives all four metrics.
- The exact Pareto frontier is reproducible.
- Equivalent winners are minimized from both parents.
- Interrupted evaluation resumes without repeating valid cached work.
- V2 discovery captures the complete raw lattice before objective/profile
  publication, reports the request and unresolved IDs at their documented JSON
  locations, and exits incomplete.
- Sealing exactly one authority per unresolved content group permits a rerun
  that reuses every compatible raw capture and publishes the exact frontier.
- Exact-content aliases inherit one approval, while a sidecar cannot replace an
  automatic v5 proof.

Hermetic checkdiff, pcdump, and inspector snapshots exercise the production
parsers. CLI tests cover help/golden output, JSON schema, ambiguity diagnostics,
budget overflow, provisional mode, reviewed discovery/sealing/resume, and
interrupted infrastructure.

### 15.3 Real-case acceptance

Run the command on the retained approximately 99.84% wrapper source and 99.66%
direct source for `mnDiagram_DrawFighterHeaders`. Acceptance requires:

- A complete four-axis profile for both parents and every successfully
  compiled, viable hybrid.
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
