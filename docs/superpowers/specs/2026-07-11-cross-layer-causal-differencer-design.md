# Cross-Layer Causal Differencer Design

Date: 2026-07-11

Status: Revised after independent review; awaiting written-spec approval before implementation planning

## Summary

Add `melee-agent debug inspect causal-diff`, a generic, read-only analyzer that
compares two already-generated compiler-artifact frontiers. Starting from one
retail instruction offset, it aligns the corresponding candidate instructions
and joins each instruction to backend virtual registers, allocator graph nodes
and decisions, mwcc-inspect Statements/ENodes/ObjObjects, stack homes, inline
scopes, and C expressions. It then compares the two evidence graphs and emits a
strict causal verdict, a lower-confidence candidate cause, or an explicit
abstention.

The first required calibration is `mnDiagram_DrawFighterHeaders`. Its paired
wrapper frontier has the desired row-register coloring but the wrong row stack
home; its direct-column frontier has exact stack homes but four wrong register
colors. The tool must explain that trade without hardcoding the function,
symbol names, virtual numbers, IG numbers, or expected conclusion.

The analyzer will use a typed, versioned evidence model behind a storage-neutral
query interface. Version 1 uses an in-memory implementation. A future persistent
provenance database can ingest the same normalized records and implement the
same query interface without changing alignment, differencing, inference, or
rendering.

## Context

The repository already exposes most required facts through separate tools:

- `debug inspect virtual-to-ig` maps visible PCode virtuals to allocator nodes.
- `debug inspect explain-virtual` reports first definitions, live spans,
  interference, and best-effort source attribution.
- `debug inspect first-divergence` identifies allocator decision divergence.
- `debug inspect lifetime-pressure` compares allocator pressure and candidate
  frontiers.
- `debug inspect stack-homes` and `frame-reservations` explain stack layout.
- `debug retro backend` and `backend-candidate` expose exact retail backend and
  allocator traces.
- `mwcc-inspect` exposes Statements, expression trees, ObjObjects, and local
  ordering.
- `role_descriptor.py`, `role_matcher.py`, and `role_reanchor.py` provide the
  established cross-compile identity mechanism.

The missing capability is a semantic join across these layers. Current
workflows force a matching agent to manually correlate a retail diff row with a
candidate instruction, PCode virtual, allocator node, inspector object, stack
home, and inline-expanded source expression. The tools can show correlation at
each layer but cannot state which source object simultaneously explains an
allocator improvement and a frame-layout regression.

Issue #1225 records this gap for `mnDiagram_DrawFighterHeaders`. Issue #1224 is
a related identity regression: reused physical registers can cause inverse
color mapping to select a later IG rather than the row-loop IG. The causal
differencer must not inherit that failure by treating physical-register reuse
or raw IG numbers as cross-compile identity.

## Decisions

The approved design makes these decisions explicit:

- Version 1 is diagnostic and read-only. It may emit exact follow-up commands,
  but it does not generate, apply, or validate source mutations.
- The primary workflow consumes two artifact-bundle manifests. It does not run
  compilers, inspectors, builds, or remote services.
- One retail instruction offset is the primary anchor. Existing role tooling
  reanchors the corresponding backend roles in both frontiers.
- Raw instruction indexes, virtuals, IG numbers, ObjObject addresses, ENode
  addresses, and stack offsets are scoped to one compile.
- Causal language is fail-closed. Ambiguous or incomplete evidence produces a
  candidate cause or abstention, never an overstated conclusion.
- The implementation is generic. `mnDiagram_DrawFighterHeaders` is a required
  end-to-end pilot, not a special analysis path.
- The normalized evidence contract and query interface form the seam for a
  future persistent provenance database.

## Goals

- Trace a selected retail instruction through all available compiler layers in
  each frontier.
- Compare the two traces using stable roles rather than raw compiler IDs.
- Explain simultaneous allocator and stack-layout effects in source-actionable
  terms.
- Preserve every fact's artifact provenance, confidence, and derivation.
- Distinguish observed facts, deterministic derived facts, and heuristics.
- Emit stable human-readable and JSON reports.
- Reuse existing parsers, frame models, allocator models, and role matching.
- Support partial diagnostics when some layers are missing while withholding
  conclusions that require those layers.
- Make future persistent storage additive rather than a redesign.

## Non-Goals

- No broad permuter, source-family search, or new mutation generator.
- No default or optional mode that edits repository source.
- No compiler instrumentation project or new retail-trace producer.
- No silent generation or refresh of missing artifacts.
- No new cross-compile identity system parallel to the existing role tools.
- No historical indexing, cross-run deduplication, migrations, retention
  policy, or multi-candidate corpus queries in version 1.
- No claim that a front-end object maps to a backend virtual solely because
  their names, ordinal positions, or numeric IDs look similar.
- No requirement to prove every compiler optimization globally. Analysis is
  target-centered around the selected retail instruction and its relevant
  dependency subgraph.

## Architecture

The implementation will live in a focused `src.mwcc_debug.causal_diff`
package. The package has eight responsibilities with one-way dependencies.

### Bundle loader

`bundles.py` parses `causal-frontier-bundle.v1` manifests, resolves artifact
paths relative to the manifest, verifies content digests, and enforces function
and compiler compatibility. It yields validated artifact references; it does
not parse compiler formats. After adapters parse those references, the command
applies the separate capability gate defined by the bundle contract.

### Artifact adapters

Adapters convert existing producer formats into normalized evidence records:

- `asm_adapter.py` consumes candidate assembly and checkdiff rows.
- `backend_adapter.py` consumes PCode dumps or `backend-trace.v1.json`.
- `inspect_adapter.py` parses mwcc-inspect Statements, ENode trees, ObjObjects,
  local orderings, and inline-expanded expressions.
- `frame_adapter.py` consumes frame reports or derives them through existing
  frame-reservation APIs from PCode and assembly.
- `source_adapter.py` resolves source spans and inline-scope descriptions.

Adapters must call existing parser/model APIs when those APIs already own the
facts. They may add narrow semantic parsing where the repository currently
only exposes text snapshots. They must not fork allocator, frame, or role
models into independent implementations.

### Evidence query interface

`store.py` defines a read-only `EvidenceQuery` protocol and an ingestion-only
`EvidenceSink` protocol. The analyzer depends only on `EvidenceQuery`.

`EvidenceSink` has these idempotent operations:

```text
add_nodes(records)
add_edges(records)
add_comparisons(records)
```

Adding an existing record ID with byte-identical canonical content is a no-op.
Adding the same ID with different content is an input-integrity error.
Each `add_*` call is atomic. The command completes bundle validation and
normalization before the first insert, so a failed bundle cannot produce a
partially analyzable dataset.

`EvidenceQuery` has these operations:

```text
get_node(record_id)
get_edge(record_id)
neighbors(record_id, edge_kinds=None, direction="both")
find_nodes(compile_id, node_kind=None, role_key=None)
find_edges(compile_id, edge_kind=None, endpoint=None)
find_comparisons(analysis_id, relation_kind=None, endpoint=None)
subgraph(seed_ids, edge_kinds, max_depth)
provenance(record_id)
```

All collection-returning operations return immutable tuples in canonical
order. Nodes sort by `(kind, role_key or "", record_id)`. Edges sort by
`(kind, source_id, target_id, record_id)`. Comparison records sort by
`(relation_kind, left_compile_id, left_record_id or "", right_compile_id,
right_record_id or "", record_id)`. `subgraph` uses breadth-first traversal,
expands neighbors in that same order, and returns canonically ordered nodes and
edges. No store may use insertion order or storage-engine row order as a
tie-breaker.
Singular getters return the immutable record or `None`; filters use exact enum
and identifier equality; `direction` accepts only `in`, `out`, or `both`.
Queries have no side effects.

Records serialize as UTF-8 using RFC 8785 JSON Canonicalization Scheme; schemas
forbid NaN and infinities, and arrays preserve schema-defined order. A node
local key is the adapter-owned tuple of artifact digest, raw span or producer
record ID, and node-kind discriminator. An edge local key is `(kind,
source_record_id, target_record_id, derivation_rule, occurrence_ordinal)`.
Record IDs hash the canonical schema version, scope ID, kind, and local key.

`InMemoryEvidenceStore` implements both protocols for version 1. A future
persistent store may use relational tables, a graph database, or another
representation, but it must expose the same semantics. Storage-specific IDs
must not leak into evidence records or analysis output.

### Retail anchor and role alignment

`alignment.py` resolves the selected retail offset in the expected assembly,
aligns it to each frontier's candidate instruction through checkdiff evidence,
and identifies the candidate instruction's use/def roles. It delegates
cross-compile identity to existing role descriptors and matchers.

An alignment result is unique only when the retail row, candidate instruction,
register class, normalized operation neighborhood, and role matcher agree. A
physical-register match is supporting evidence only; it is not identity because
retail can reuse the same physical register for multiple non-overlapping roles.

Expert overrides may nominate a per-frontier backend node for one explicit
anchor operand position when automatic alignment abstains. Overrides are
reported as user assertions and do not become observed evidence. They cannot
change the retail expected register or create/remove primary effects. A causal
verdict still requires the remaining ownership chain to pass all proof gates.

### Evidence graph builder

`graph.py` constructs a compile-scoped typed graph for each frontier. It stores
raw facts and within-compile joins but does not infer causes. It also constructs
comparison-scoped correspondence records after role alignment; these are not
inserted as edges in either compile-scoped graph.

### Cross-frontier differencer

`differ.py` consumes comparison records to compare role-aligned subgraphs. It
classifies changes without assigning causality.

### Causal inference engine

`inference.py` applies small, explicit, table-tested rules to graph deltas. It
emits verdict records with cited proof paths and failed gates. Rules consume
normalized evidence only; they do not read raw artifacts or storage internals.

### Renderers

`render.py` produces stable text and `causal-diff-report.v1` JSON. Rendering is
pure and cannot change analysis state or confidence.

## Command Surface

Primary command:

```bash
melee-agent debug inspect causal-diff \
  -f mnDiagram_DrawFighterHeaders \
  --frontier paired=paired.frontier.json \
  --frontier direct=direct.frontier.json \
  --retail-offset 0x120
```

Version 1 options:

```text
-f, --function FUNCTION       required function name
--frontier LABEL=MANIFEST     exactly two uniquely labeled frontiers
--retail-offset OFFSET        required function-relative retail byte offset
--frontier-node LABEL:OPERAND=SPEC
                              optional expert node assertion, repeatable;
                              OPERAND is def:N or use:N; SPEC is class:ig or
                              a virtual token
--json                        emit causal-diff-report.v1 JSON
--evidence-depth N            dependency traversal bound, default 4, maximum 8
```

The traversal bound limits graph expansion, not evidence ingestion. If the
proof path would exceed the bound, the report identifies the truncated edge and
abstains. Version 1 has no compile, refresh, apply, or validation options.

Paths in a manifest resolve relative to that manifest. Labels appear only in
presentation and report keys; analysis never assigns special semantics to
`paired`, `direct`, `left`, or `right`. Labels match `[A-Za-z0-9_-]+`, and the
CLI label must equal `manifest.label`; a mismatch is an input error.

## Artifact Bundle Contract

Each `causal-frontier-bundle.v1` manifest describes one immutable compile:

The repeated hexadecimal digits below are illustrative values with the required
digest length; real manifests contain computed digests.

```json
{
  "schema_version": "causal-frontier-bundle.v1",
  "label": "paired",
  "function": "mnDiagram_DrawFighterHeaders",
  "compile": {
    "id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "compiler": "mwcc_233_163n",
    "target_build": "GALE01",
    "flags_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "environment_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "source_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "expected_assembly_digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333"
  },
  "artifacts": {
    "source": {"path": "paired.c", "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},
    "checkdiff": {"path": "paired.checkdiff.json", "sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},
    "backend": [
      {
        "path": "paired.pcdump.txt",
        "sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "format": "mwcc-debug-pcdump",
        "capabilities": [
          "pcode-occurrences",
          "virtual-use-def",
          "virtual-to-allocator-node",
          "allocator-decisions",
          "interference-edges"
        ]
      }
    ],
    "inspector": {"path": "paired.inspect.txt", "sha256": "1111111111111111111111111111111111111111111111111111111111111111"},
    "frame_report": {"path": "paired.frame.json", "sha256": "2222222222222222222222222222222222222222222222222222222222222222"}
  },
  "producer_versions": {
    "checkdiff": "checkdiff-json.v1",
    "mwcc_debug": "mwcc-debug-pcdump.v1",
    "mwcc_inspect": "mwcc-inspect-text.v1"
  }
}
```

Required artifacts are:

- source;
- checkdiff JSON containing expected and current instruction rows;
- one or more backend artifacts whose verified union provides
  `pcode-occurrences`, `virtual-use-def`, `virtual-to-allocator-node`,
  `allocator-decisions`, and `interference-edges`;
- mwcc-inspect output containing the requested function.

The five backend capability names above are the complete version 1 core
contract. Each backend format adapter has a fixed set of capabilities it can
verify from parsed content. Manifest declarations select expected capabilities
but cannot grant them: after parsing, the adapter emits its verified capability
set, and the command rejects a bundle whose verified union lacks a required
capability. An allocator-only trace without PCode occurrences and virtual
use-def evidence is therefore invalid unless the bundle also includes a PCode
artifact that supplies those capabilities. Unknown capability names are a
schema error.

`frame_report` is optional when the existing frame APIs can deterministically
derive equivalent evidence from the supplied PCode/backend and assembly data.
The report records whether frame evidence was supplied or derived.

Both frontiers must have identical `expected_assembly_digest`, compiler
identity, `target_build`, optimization-flags digest, and `environment_digest`.
The environment digest covers included headers, configuration inputs, and other
toolchain context shared by both candidate compilations; it deliberately
excludes the translation-unit source bytes. Each frontier has its own
`source_digest`, which must equal the digest of its source artifact. Paired and
direct frontiers therefore share an environment while retaining distinct
compile IDs and compile-local namespaces. Producer versions and run metadata
remain separate provenance. A digest or compile-ID mismatch is an input error,
not a freshness warning.

`compile.id` is the SHA-256 digest of a canonical record containing the
function, compiler identity, target/build version, flags digest, environment
digest, and per-frontier source digest. It does not include timestamps,
filesystem paths, or producer versions.

Manifests reference artifacts rather than embedding large logs. Normalized
records preserve the manifest, artifact path, digest, and raw byte/line span so
a future database can re-verify provenance.

## Normalized Evidence Model

Every compile-scoped node and edge has:

```text
record_id       SHA-256 of schema version, compile ID, kind, and local key;
                stable across repeated ingestion of the same evidence
compile_id      immutable identity of one frontier compile
function        owning function
kind            versioned node or edge kind
role_key        optional cross-compile role descriptor, never a raw compiler ID
producer_confidence
                confidence declared by the producer fact contract
adapter_confidence
                confidence of parsing or joining that fact
confidence      weakest(producer_confidence, adapter_confidence)
provenance      artifact digest, parser, raw span, and derivation rule
attributes      kind-specific structured fields
```

Both endpoints of a compile-scoped edge must have the edge's `compile_id`.
Cross-frontier relationships use a separate comparison record:

```text
record_id
analysis_id       SHA-256 of label-sorted (label, compile ID) pairs, retail
                  offset, traversal bound, and normalized expert assertions
relation_kind     role-corresponds-to | node-added | node-removed |
                  node-changed | edge-added | edge-removed | edge-changed
left_compile_id
left_record_id    nullable only for added relations
right_compile_id
right_record_id   nullable only for removed relations
confidence
provenance
attributes
```

Comparison records never acquire a `compile_id` and never enter either
frontier's compile-scoped graph. Repeating the same analysis inputs produces
the same `analysis_id` and comparison record IDs. `left` is the
lexicographically first frontier label and `right` is the second.

### Node kinds

- `retail-instruction`: function-relative offset, opcode, operands, normalized
  neighborhood signature.
- `candidate-instruction`: candidate offset/index, opcode, operands, aligned
  retail row.
- `pcode-occurrence`: pass, block, instruction index, opcode, operands, use/def
  position.
- `virtual-register`: class, virtual number, definitions, uses, live ranges.
- `allocator-node`: class, compile-scoped IG number, degree, interference,
  simplify/select order, coalesce root, assigned physical register.
- `allocator-decision`: decision iteration, available/blocked registers,
  blockers, and selected register.
- `statement`: inspector statement identity, order, raw span, expression root.
- `enode`: ENode opcode, tree path, normalized expression, children.
- `objobject`: compile-scoped inspector address, name, data/type class, local
  order, synthetic-name status, and owning inline scope.
- `stack-object`: symbolic name when available, offset, size, kind, access
  interval, assignment order, and source classification.
- `source-expression`: source span, normalized C expression, enclosing
  statement, and inline expansion path.
- `inline-scope`: caller/callee path and source definition/call-site spans when
  recoverable.

ObjObject addresses and synthetic names such as `@1862` are stored only as
compile-local attributes. A stable role key derives from type, normalized
defining expression, statement/ENode context, scope path, consumers, and local
order. The role matcher may use that key across frontiers, but it must report
ambiguity rather than selecting by nearest ordinal.

### Edge kinds

- `aligns-to-retail`: checkdiff-backed candidate instruction alignment.
- `uses-virtual` and `defines-virtual`: instruction/PCode use-def links.
- `maps-to-allocator-node`: existing virtual-to-IG mapping.
- `has-color-decision`, `interferes-with`, and `coalesces-with`: allocator facts.
- `statement-has-enode` and `enode-child`: inspector tree structure.
- `enode-references-object`: explicit inspector `EOBJREF -> ObjObject` links.
- `object-owned-by-scope`: inspector/source scope ownership.
- `expression-represents-enode`: source/inspector expression alignment.
- `lowers-to`: front-end expression/object to PCode role attribution.
- `materializes-as-stack-object`: ObjObject/backend value to stack-home link.

`role-corresponds-to` is a comparison relation, not a compile-scoped edge.

## Evidence Strength and Joins

Evidence is divided into three classes.

### Observed

The primary producer contract identifies the relationship as a raw observation,
and the adapter parses it without an additional inference. Examples include an
ENode child, `EOBJREF` to an ObjObject, a raw virtual-to-IG event, an emitted
interference edge, an allocator decision event, or a checkdiff row. Merely
serializing a derived statement in a frame or attribution report does not make
it observed.

### Derived unique

A deterministic join has exactly one compatible result and cites all inputs.
Examples include:

- a uniquely aligned candidate instruction selected by one retail row and
  opcode-neighborhood signature;
- a named or symbolic stack home that resolves to exactly one ObjObject/backend
  value in the same compile;
- an inspector expression whose normalized operation tree, object references,
  consumer call, type, and order identify exactly one PCode def-use chain;
- a role match accepted by the existing matcher with no equally ranked role.

Derived-unique edges are proof-capable. The report must include the derivation
rule and rejected alternatives.

### Heuristic

A scored join has multiple compatible results or relies on a weak signal such
as declaration order, a compiler-temp ordinal, a name-only match, or a partial
operation signature. Heuristic edges may support a candidate-cause report and
next-step guidance. They may not appear in a proof path for a `causes` verdict.

Confidence propagates through the lattice `observed > derived-unique >
heuristic`. A normalized record's effective confidence is the weaker of the
producer fact's declared confidence and the adapter's parse/join confidence.
For a derived edge, it is also no stronger than the weakest input record. If a
producer format omits confidence for a fact that its versioned contract does
not designate as a raw observation, the adapter assigns `heuristic`.
Consequently, importing a precomputed frame or attribution report cannot
launder a heuristic producer conclusion into proof-capable evidence.

The semantic mwcc-inspect adapter is the main new parser work. The current
`inspect_parser.py` only slices text sections. The adapter must conservatively
parse the existing indentation-based statement/ENode tree and explicit
ObjObject references while retaining raw spans. Unsupported lines remain raw
records with warnings and do not create guessed edges.

## Data Flow

Analysis proceeds in this order:

1. Load both manifests and validate file digests plus declared function,
   expected-assembly, and toolchain compatibility.
2. Normalize each artifact independently; adapters verify parsed function,
   expected-assembly digest, producer confidence, and capabilities against the
   manifest.
3. Apply the version 1 capability gate before any evidence insertion.
4. Ingest records into `InMemoryEvidenceStore` under separate compile IDs.
5. Resolve the retail instruction at `--retail-offset`.
6. Align the retail row to one candidate instruction in each frontier.
7. Derive the ordered primary allocator-effect set from the anchor's register
   operands and expected physical registers.
8. Build target-centered backend roles from instruction/PCode use-def evidence.
9. Reanchor corresponding roles through existing role matchers and store the
   results as comparison records.
10. Traverse allocator, front-end, stack, inline-scope, and source ownership
   edges up to the configured depth.
11. Derive reachable stack effects and eligible allocator/stack effect pairs.
12. Compute role-aligned node and edge deltas.
13. Apply causal inference gates and rules to each eligible effect pair.
14. Render the shortest proof/candidate paths, material deltas, missing
    evidence, and read-only follow-up commands.

## Deterministic Effect Derivation

The retail offset is both the alignment anchor and the source of the primary
effect set. The analyzer parses the retail instruction with the existing opcode
semantics and assigns every register operand an ordered semantic position such
as `def:0`, `use:0`, or `use:1`. The expected physical register is the retail
operand at that position. The aligned candidate instruction and its
PCode/allocator chain provide each frontier's current physical register.

One primary allocator effect is emitted for every register operand position
that resolves to a unique role in both frontiers. Definitions sort before uses,
then by operand position and role key. If an opcode ties the same role across
multiple positions, those positions merge into one effect. An unresolved
position produces a per-position abstention record and does not change the
identity or ordering of other effects.

Each frontier's quality for an allocator effect is `exact` when its assigned
physical register equals retail and `mismatch` otherwise. The two-frontier
direction is one of:

```text
first-exact-second-mismatch
first-mismatch-second-exact
both-exact
both-mismatch-same
both-mismatch-different
```

`first` and `second` refer to frontier labels sorted lexicographically, not CLI
argument order.

After the primary roles are known, the analyzer traverses their complete
source/backend ownership subgraphs within `--evidence-depth`. It emits a stack
effect for every reachable expected stack-object role that:

1. resolves without ambiguity to zero or one object in each frontier, with at
   least one frontier object present;
2. has an expected retail offset/size from expected frame or stack-localizer
   evidence; and
3. differs in offset, size, assignment order, or materialization interval
   between the frontiers.

Stack effects use the same five direction values. A present object is `exact`
when its offset and size equal retail; an absent object is `mismatch`.
Assignment-order or interval changes remain attributes even when both offsets
are exact. Stack effects sort by role key and then comparison record ID.

An eligible dual-effect pair contains one primary allocator effect and one
reachable stack effect for which the same frontier is allocator-exact while the
other is allocator-mismatched, and that allocator-exact frontier is
stack-mismatched while the other is stack-exact. This is the precise meaning of
allocator “improvement” plus stack “regression.” Both-mismatch and both-exact
effects remain in the report but do not enter the version 1 dual-effect rule.
Multiple operand roles and multiple reachable stack roles are evaluated as
separate, canonically ordered pairs; the engine never merges their verdicts.

If no eligible pair exists and the target-centered graphs are complete, the
analysis emits `no-causal-difference`. If no pair exists because required
identity, expected-layout, or traversal evidence is incomplete, it emits
`abstain` with the missing effect-construction gate.

## Graph Delta Model

The differencer classifies role-aligned changes as:

- node added or removed;
- ownership edge added, removed, or redirected;
- live/access interval shortened, extended, split, or merged;
- stack object added, removed, moved, resized, or reordered;
- simplify/select/color decision reordered;
- allocator node recolored, coalesced differently, or blocked by a different
  role;
- front-end expression folded, materialized, or moved across an inline scope;
- evidence unresolved or contradictory.

The differencer reports facts only. For example, it may report that the paired
frontier adds a `fighter_id` assignment ObjObject, moves a row role later in
select order, and adds or extends a stack ownership path. It does not call that
ObjObject causal until the inference engine validates a proof path.

## Causal Verdicts

`causes` is an operational compiler-evidence verdict: within the compared,
target-centered graphs, one uniquely changed ownership/dependency chain
mediates both queried effects and every link is proof-capable. It is not a claim
that two observational samples establish unrestricted program causality outside
the captured compiler layers. The report states this scope next to every
`causes` verdict.

Each eligible allocator/stack effect pair receives one of four statuses:

- `causes`: all proof gates pass.
- `candidate-cause`: anchor/effect identities are resolved and the graph is
  complete, but an expert assertion or the finite causal alternatives include
  heuristic paths or more than one complete owner chain.
- `no-causal-difference`: the relevant ownership/dependency path is unchanged.
- `abstain`: anchor/effect identity, graph completeness, required evidence, or
  consistency is insufficient to enumerate complete alternatives.

`no-causal-difference` is scoped to the version 1 dual-effect question. It
means no eligible allocator-improvement/stack-regression pair has a changed
shared mediator; it does not assert that the two full compiler graphs are
identical.

The decision table is normative:

| Anchor/effects | Graph/path state | Owner alternatives | Verdict |
|---|---|---|---|
| unique, proof-capable | complete; all path edges proof-capable | exactly one changed shared owner chain | `causes` |
| unique, proof-capable | complete; at least one complete path | finite known alternatives, or a path contains heuristic edges | `candidate-cause` |
| resolved by an explicit expert assertion | complete; at least one complete path | finite known alternatives | `candidate-cause` |
| unique, proof-capable | complete; no shared changed path | none | `no-causal-difference` |
| missing or ambiguous without an assertion | any | any | `abstain` |
| unique | incomplete, truncated, or contradictory | cannot enumerate completely | `abstain` |

Heuristic evidence may lower a complete enumerated path to `candidate-cause`.
It may not fill a missing segment, resolve an ambiguous effect identity, or
override a contradiction; those cases are `abstain`.

A `causes` verdict requires all of these gates:

1. The retail row aligns uniquely to one candidate instruction in each
   frontier.
2. Backend roles reanchor uniquely across frontiers.
3. The changed source expression or ObjObject owns the relevant backend
   dependency through observed or derived-unique edges.
4. The allocator decision delta is observed or derived-unique.
5. The stack-object ownership and interval/layout delta is observed or
   derived-unique.
6. The changed ownership chain is unique among material graph deltas within the
   target-centered subgraph.
7. No proof-path edge is heuristic.
8. No required artifact is missing, incompatible, truncated, digest-invalid,
   compile-environment-invalid, or contradicted by another artifact.

Failure of gates 1, 4, 5, or 8 produces `abstain`. Failure of gate 2 produces
`abstain` unless an explicit operand-scoped expert assertion resolves the
backend node; that assertion caps the result at `candidate-cause`. A finite,
complete result that fails gate 3, 6, or 7 may produce `candidate-cause`
according to the table.
Every report names the failed gate and the evidence needed to upgrade
confidence. Absence of a source mapping is not automatically classified as
compiler-generated. `compiler-generated/no-owner` requires positive evidence
that a compiler temporary lacks any source/ObjObject owner within a completely
parsed scope.

Version 1 ships a generic dual-effect rule:

```text
If one uniquely changed owner/dependency chain explains a proof-capable
allocator decision improvement and a proof-capable stack interval/layout regression, report
that owner as their shared cause and recommend preserving the allocator
dependency while testing a shorter materialization interval.
```

The rule contains no function names, ObjObject names, offsets, virtuals, IGs,
or expected registers.

## Report Contract

`causal-diff-report.v1` contains:

```text
schema_version
analysis_id
analysis_status               complete | partial | abstained
function
inputs                      manifests, artifacts, digests, producer versions
anchor                      retail instruction and alignment status
effects                     deterministic allocator/stack effects and directions
frontiers                   per-frontier target-centered evidence chains
role_correspondences        cross-frontier matches and rejected alternatives
graph_deltas                typed node/edge changes
verdicts                    status, effect, cause, proof path, failed gates
recommendations             read-only hypotheses and exact follow-up commands
missing_evidence
contradictions
warnings
```

Human output leads with the verdict and shortest supporting chain. It then
prints the allocator and stack deltas, confidence/abstention reasons, and
follow-up commands. It does not dump the full graph unless JSON is requested.

Illustrative proven output:

```text
CAUSES: paired-only wrapper assignment object O17
  source: inline path DrawFighterHeaders -> visible-header wrapper
  allocator: O17 -> value role R70 -> interference/select dependency ->
             row roles R66/R67 select later and receive target colors
  frame: O17 -> materialized value S4 -> row child home shifts 0x44 -> 0x48
  recommendation: preserve dependency edge E12 while testing a shorter
                  materialization interval for O17/S4
```

Actual output uses role descriptors and artifact citations, not assumed pilot
IDs. If the stack ownership join is heuristic, the same evidence produces
`CANDIDATE CAUSE`, not `CAUSES`.

## Exit Semantics

- Exit `2`: malformed manifests, missing files, digest mismatches, incompatible
  functions/compiler identities, or unsupported schema versions.
- Exit `3`: input validation succeeded, but global anchor alignment failed or
  every primary allocator effect/effect pair is `abstain`.
- Exit `0`: at least one primary allocator effect was fully evaluated to
  `causes`, `candidate-cause`, or `no-causal-difference`. Other per-effect
  abstentions remain in the report and set `analysis_status` to `partial`.

Partial reports are emitted for exit `3` when input validation succeeded.
Input errors do not emit a misleading partial causal report.

## Error Handling

- Unknown inspector syntax is preserved with its raw span and parse warning.
- An unknown record never creates a guessed node relationship.
- Conflicting ownership paths are retained as contradictions and force
  abstention for conclusions that depend on them.
- Missing optional frame reports may be derived only through deterministic
  existing APIs and are marked `derived`.
- Missing required evidence can still appear in a partial diagnostic but
  cannot be bypassed by a heuristic.
- User node overrides are labeled assertions and cannot upgrade evidence
  confidence.
- Traversal truncation names the frontier node and unexplored edge kinds.
- All derived and heuristic edges cite inputs, rule name, confidence, and
  rejected alternatives.
- Renderers tolerate partial records and never reinterpret missing data.

## Testing Strategy

### Schema and bundle tests

- Round-trip the bundle, compile-evidence, comparison-record, and report
  schemas.
- Reject unknown major versions.
- Reject missing `target_build`, expected-assembly digest, environment digest,
  source digest, and backend capability declarations.
- Reject missing artifacts, digest mismatches, compile-ID mismatches, different
  expected assembly/environment digests, and incompatible compiler settings.
- Accept distinct frontier source/compile IDs under one shared environment and
  reject frontiers whose compile IDs collapse despite different source digests.
- Reject a manifest capability that its adapter cannot verify and reject a
  verified backend union missing any of the five required capabilities.
- Resolve relative paths against the manifest rather than the working
  directory.

### Inspector adapter tests

- Parse minimized real statements containing nested `EASS`, `ECOMMA`,
  `EOBJREF`, ObjObject addresses/types, synthetic `@NNNN` names, local-order
  sections, and inline-expanded expressions.
- Preserve raw spans and indentation/tree structure.
- Retain unknown syntax without synthesizing edges.
- Distinguish named source locals, synthetic compiler temporaries, functions,
  data objects, and ambiguous objects.
- Preserve producer confidence from imported frame/attribution facts and prove
  that serialization cannot upgrade derived or heuristic evidence to
  `observed`.

### Evidence and storage tests

- Verify stable content-derived record IDs.
- Verify all compiler-local identifiers remain scoped by compile ID.
- Reject cross-compile endpoints on compile-scoped edges and represent role
  correspondences with comparison records under a stable analysis ID.
- Verify idempotent duplicate ingestion and reject same-ID/different-content
  ingestion.
- Insert identical records in different orders and prove every query, subgraph,
  JSON report, and text report is byte-identical.
- Run the same analyzer contract against `InMemoryEvidenceStore` and a minimal
  fake persistent store.
- Prove analysis code does not access manifest paths or in-memory containers
  directly.

### Alignment and differencing tests

- Reanchor roles when every raw virtual, IG, ObjObject address, and stack offset
  changes.
- Abstain on equally ranked roles.
- Derive register effects in canonical def/use order for multi-register anchor
  instructions and keep resolvable roles when another operand abstains.
- Derive direction from expected physical registers and expected stack homes,
  independent of CLI frontier order.
- Enumerate multiple reachable stack roles as distinct effect pairs.
- Reproduce the reused-physical-register regression from issue #1224 and prove
  the row role is selected instead of the later scan role.
- Classify ownership, interval, layout, selection-order, and color deltas.

### Inference tests

Table-driven fixtures cover:

- a unique all-proof-capable dual-effect path producing `causes`;
- the same graph with one heuristic join producing `candidate-cause`;
- multiple complete material source deltas producing `candidate-cause`;
- an incomplete path or non-enumerable ambiguity producing `abstain`;
- contradictory frame ownership forcing `abstain`;
- identical relevant subgraphs producing `no-causal-difference`;
- a user override that resolves one operand to `candidate-cause` but can never
  produce `causes`.

### CLI tests

- Golden help and concise text output.
- Stable `causal-diff-report.v1` JSON.
- Exit `0` for complete and partial analyses with at least one evaluated
  primary effect, exit `3` when all primary effects abstain, and exit `2` for
  input errors.
- No artifact generation, subprocess compiler call, source write, or repository
  mutation during analysis.

## DrawFighterHeaders Pilot

Create minimized checked-in fixtures under
`tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/` from the
existing paired-wrapper and direct-column artifacts. Fixtures must retain only
the requested function and evidence necessary for the proof; they must preserve
real syntax and provenance metadata.

The pilot test must:

1. Start from a function-relative retail offset in the row-count/coloring
   region.
2. Load two distinct source-derived compile IDs under the same expected
   assembly/toolchain environment.
3. Align the correct candidate instruction in both frontiers and derive its
   register-operand effects without a pilot-specific target list.
4. Map the row roles to the actual row-loop nodes rather than a later role that
   reuses the same physical register.
5. Parse the paired-only `fighter_id` assignment expression and ObjObject from
   mwcc-inspect without relying on that name in generic logic.
6. Join the relevant backend and stack ownership paths using observed or
   derived-unique evidence.
7. Report the paired frontier's allocator benefit and stack-layout regression
   relative to the direct frontier.
8. Produce the shared-cause explanation and preserve-dependency/shorten-
   interval recommendation with no function-specific inference rule.
9. Emit byte-identical reports through the in-memory and fake persistent
   stores.

If the real artifacts cannot support a proof-capable stack ownership edge, the
implementation must improve parsing or capture of evidence already exposed by
the approved producers, or narrow the claimed effect. New compiler
instrumentation and producer work remain outside this feature. The
implementation must not weaken the causal gate to make the pilot pass.

## Future Persistent Provenance Database

Version 1 deliberately prepares for persistence without implementing it:

- Bundle and report schemas are versioned import/export contracts.
- Evidence records are serializable, content-derived, compile-scoped, and
  provenance-bearing.
- Comparison records are analysis-scoped and preserve both endpoint compile
  identities.
- Analyzer queries are storage-neutral.
- Query ordering, traversal, serialization, and duplicate-ingestion semantics
  are normative and store-independent.
- Ingestion is separated from read-only analysis.
- Cross-compile identity is represented by role evidence, not database IDs.
- Raw artifact references and spans remain available for re-verification.

A later database project may add historical ingestion, indexes, deduplication,
schema migrations, artifact retention, and multi-frontier queries. Those
features should implement or extend the store protocols while leaving the
causal analysis engine unchanged. If future query requirements exceed the
version 1 protocol, the protocol should be versioned and extended rather than
allowing persistence concerns into inference rules.

## Completion Criteria

The feature is complete when:

- `debug inspect causal-diff --help` documents the approved read-only command.
- Two validated bundles can be analyzed from one retail offset.
- The frontiers share an expected/toolchain environment but retain distinct
  source-derived compile IDs.
- Backend adapters verify the complete version 1 capability contract.
- All normalized facts retain provenance and confidence.
- Effective confidence never exceeds producer or adapter confidence.
- Raw compiler IDs never serve as cross-compile identity.
- Cross-frontier relations are comparison-scoped rather than compile-scoped
  edges.
- The semantic inspector adapter exposes Statements, ENodes, ObjObjects, local
  order, and inline-expanded expressions conservatively.
- The anchor deterministically produces ordered allocator effects, reachable
  stack effects, and eligible dual-effect pairs.
- The differencer reports allocator, ownership, and stack deltas independently
  of inference.
- Causal rules enforce every proof gate and strict abstention.
- Human and JSON reports satisfy their stable contracts.
- Unit, integration, CLI, canonical-ordering, and store-conformance tests pass.
- The generic `mnDiagram_DrawFighterHeaders` pilot produces the required
  cross-layer explanation without hardcoded case logic.
- Default and expert-override modes perform no source or artifact mutation.
