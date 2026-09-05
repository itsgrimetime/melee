# Cross-Layer Causal Differencer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic, read-only `melee-agent debug inspect causal-diff` command that joins two compiler-artifact frontiers from one retail instruction through backend allocation, mwcc-inspect objects, stack homes, inline-expanded source, and a strict causal verdict.

**Architecture:** Normalize immutable artifacts into compile-scoped evidence graphs and analysis-scoped comparison records behind a deterministic query protocol. Reuse the existing role, allocator, frame, stack-slot, PCode, and source-attribution implementations; add only the semantic mwcc-inspect parser and cross-layer orchestration they lack. Derive effects deterministically from the retail instruction, then apply explicit inference and abstention rules.

**Tech Stack:** Python 3.11, Typer, Pydantic 2, `rfc8785==0.1.4`, pytest, existing `src.mwcc_debug` parsers and analyzers.

## Global Constraints

- Run commands from `/Users/mike/.codex/worktrees/b8fa/melee`; run branch-local CLI tests from `tools/melee-agent` with `python -m src.cli`.
- `causal-diff` is read-only: it must not compile, invoke remote services, edit source, refresh artifacts, or mutate repository/build state.
- Version 1 accepts exactly two labeled `causal-frontier-bundle.v1` manifests and one function-relative retail byte offset.
- The required backend capability set is exactly `pcode-occurrences`, `virtual-use-def`, `virtual-to-allocator-node`, `allocator-decisions`, and `interference-edges`.
- Frontier compile IDs include their distinct source digests; compiler, `GALE01`, flags, environment, and expected-assembly digests must match.
- Raw virtuals, IG IDs, ObjObject addresses, ENode positions, and stack offsets are compile-scoped and never establish cross-frontier identity.
- Cross-frontier identity must reuse `role_descriptor.py`, `role_matcher.py`, and `role_reanchor.py`.
- Effective confidence is the weakest of producer, adapter, and input-edge confidence; serialized derived facts never become observed facts.
- Only complete proof-capable paths may emit `causes`; complete finite heuristic alternatives emit `candidate-cause`; missing, truncated, contradictory, or non-enumerable paths emit `abstain`.
- Query ordering, RFC 8785 serialization, record IDs, traversal, and duplicate-ingestion behavior must be identical across stores.
- `mnDiagram_DrawFighterHeaders` is a fixture-backed pilot only; production code must not mention its name, source identifiers, offsets, registers, or expected verdict.
- Every task uses test-first development and ends with a focused commit.

## File Map

Create these focused modules under `tools/melee-agent/src/mwcc_debug/causal_diff/`:

- `__init__.py`: stable public exports only.
- `canonical.py`: RFC 8785 serialization and SHA-256 record IDs.
- `models.py`: immutable core evidence and comparison records.
- `store.py`: `EvidenceSink`, `EvidenceQuery`, `EvidenceStore`, and deterministic in-memory store.
- `bundles.py`: manifest models, digest verification, pair compatibility, and capability declarations.
- `inspect_adapter.py`: semantic mwcc-inspect records to evidence nodes/edges.
- `asm_adapter.py`: checkdiff rows, expected/candidate instructions, retail offsets, and stack-localizer facts.
- `backend_adapter.py`: PCode/backend traces to virtual, allocator, decision, and interference evidence.
- `frame_adapter.py`: frame reports and stack-slot bridges to stack-object evidence.
- `source_adapter.py`: source expressions, direct-inline scope paths, and source/ENode candidates.
- `graph.py`: within-compile proof-capable and heuristic joins.
- `alignment.py`: retail-row alignment, operand-scoped expert assertions, and role correspondences.
- `effects.py`: canonical allocator/stack effects and eligible dual-effect pairs.
- `differ.py`: comparison-scoped graph delta records.
- `inference.py`: decision table, proof gates, verdicts, and exit aggregation.
- `render.py`: stable text and JSON rendering.
- `commands.py`: bundle-to-report orchestration with no subprocesses or writes.

Modify existing files only where they own the integration seam:

- `tools/melee-agent/src/mwcc_debug/inspect_parser.py`: semantic parser beside the existing snapshot parser.
- `tools/melee-agent/src/cli/debug/inspect.py`: Typer leaf command.
- `tools/melee-agent/src/cli/capabilities.py`: intent aliases for the new command.
- `tools/melee-agent/pyproject.toml`: pin `rfc8785==0.1.4`.
- `docs/CAPABILITIES.md`: generated command inventory.

---

### Task 1: Canonical Records and Deterministic Store

**Files:**
- Modify: `tools/melee-agent/pyproject.toml`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/__init__.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/canonical.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/models.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/store.py`
- Create: `tools/melee-agent/tests/test_causal_diff_store.py`

**Interfaces:**
- Consumes: RFC 8785 `dumps(value) -> bytes`.
- Produces: `Confidence`, `Provenance`, `EvidenceNode`, `EvidenceEdge`, `ComparisonRecord`, `AdapterResult`, `canonical_bytes`, `stable_id`, `EvidenceSink`, `EvidenceQuery`, `EvidenceStore`, and `InMemoryEvidenceStore`.

- [ ] **Step 0: Re-run the repository capability audit at execution time**

```bash
melee-agent capabilities search "cross-layer causal compiler provenance differencer"
```

Expected: the search identifies the reusable allocator, frame, stack-home, inspector, and source-attribution commands described in this plan, but no existing command that performs the complete cross-layer causal join. If an exact capability has appeared since this plan was written, stop and revise the plan around reuse before adding code.

- [ ] **Step 1: Add failing canonicalization and store-contract tests**

```python
from __future__ import annotations

import pytest

from src.mwcc_debug.causal_diff.models import (
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore


def _prov() -> Provenance:
    return Provenance(
        artifact_sha256="a" * 64,
        parser="unit-test.v1",
        raw_start=10,
        raw_end=20,
        derivation_rule="raw",
    )


def _node(compile_id: str, local_key: str, role_key: str) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=compile_id,
        function="fn_test",
        kind="virtual-register",
        local_key=local_key,
        role_key=role_key,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes={"virtual": int(local_key)},
    )


def test_record_ids_are_rfc8785_stable() -> None:
    first = _node("compile-a", "66", "row-counter")
    second = EvidenceNode.create(
        compile_id="compile-a",
        function="fn_test",
        kind="virtual-register",
        local_key="66",
        role_key="row-counter",
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_prov(),
        attributes={"virtual": 66},
    )
    assert first.record_id == second.record_id


def test_store_queries_ignore_insertion_order() -> None:
    a = _node("compile-a", "66", "row-counter")
    b = _node("compile-a", "67", "row-count")
    left = InMemoryEvidenceStore()
    right = InMemoryEvidenceStore()
    left.add_nodes((b, a))
    right.add_nodes((a, b))
    assert left.find_nodes("compile-a") == right.find_nodes("compile-a")
    assert [node.record_id for node in left.find_nodes("compile-a")] == sorted(
        (a.record_id, b.record_id)
    )


def test_compile_edges_reject_cross_compile_endpoints() -> None:
    store = InMemoryEvidenceStore()
    a = _node("compile-a", "66", "row-counter")
    b = _node("compile-b", "70", "fighter-id")
    store.add_nodes((a, b))
    edge = EvidenceEdge.create(
        compile_id="compile-a",
        function="fn_test",
        kind="lowers-to",
        source_id=a.record_id,
        target_id=b.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_prov(),
        attributes={},
    )
    with pytest.raises(ValueError, match="cross-compile edge"):
        store.add_edges((edge,))


def test_duplicate_id_with_different_content_is_rejected() -> None:
    store = InMemoryEvidenceStore()
    node = _node("compile-a", "66", "row-counter")
    store.add_nodes((node,))
    altered = node.with_attributes({"virtual": 67})
    with pytest.raises(ValueError, match="record ID collision"):
        store.add_nodes((altered,))
```

- [ ] **Step 2: Run the tests and confirm the package is absent**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_store.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'src.mwcc_debug.causal_diff'`.

- [ ] **Step 3: Add the pinned canonicalization dependency and immutable record model**

Add `"rfc8785==0.1.4",` to `[project].dependencies`, then implement these exact public shapes:

```python
class Confidence(StrEnum):
    HEURISTIC = "heuristic"
    DERIVED_UNIQUE = "derived-unique"
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class Provenance:
    artifact_sha256: str
    parser: str
    raw_start: int | None
    raw_end: int | None
    derivation_rule: str
    input_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    record_id: str
    compile_id: str
    function: str
    kind: str
    role_key: str | None
    producer_confidence: Confidence
    adapter_confidence: Confidence
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    record_id: str
    compile_id: str
    function: str
    kind: str
    source_id: str
    target_id: str
    producer_confidence: Confidence
    adapter_confidence: Confidence
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    record_id: str
    analysis_id: str
    relation_kind: str
    left_compile_id: str
    left_record_id: str | None
    right_compile_id: str
    right_record_id: str | None
    confidence: Confidence
    provenance: Provenance
    attributes: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AdapterResult:
    nodes: tuple[EvidenceNode, ...] = ()
    edges: tuple[EvidenceEdge, ...] = ()
    verified_capabilities: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
```

`canonical_bytes(value)` must return `rfc8785.dumps(value)`. `stable_id(scope_id, kind, local_key)` must SHA-256 the canonical mapping `{"schema_version": "causal-evidence.v1", "scope_id": scope_id, "kind": kind, "local_key": local_key}`. Factory methods compute effective confidence with `min_confidence` using `HEURISTIC < DERIVED_UNIQUE < OBSERVED`; derived records also include input confidences in that minimum. `with_attributes` preserves the original record ID so the collision test can verify integrity enforcement.

- [ ] **Step 4: Implement the deterministic protocols and in-memory store**

```python
class EvidenceSink(Protocol):
    def add_nodes(self, records: Iterable[EvidenceNode]) -> None:
        raise NotImplementedError

    def add_edges(self, records: Iterable[EvidenceEdge]) -> None:
        raise NotImplementedError

    def add_comparisons(self, records: Iterable[ComparisonRecord]) -> None:
        raise NotImplementedError


class EvidenceQuery(Protocol):
    def get_node(self, record_id: str) -> EvidenceNode | None:
        raise NotImplementedError

    def get_edge(self, record_id: str) -> EvidenceEdge | None:
        raise NotImplementedError

    def neighbors(
        self,
        record_id: str,
        edge_kinds: frozenset[str] | None = None,
        direction: Literal["in", "out", "both"] = "both",
    ) -> tuple[EvidenceEdge, ...]:
        raise NotImplementedError

    def find_nodes(
        self,
        compile_id: str,
        node_kind: str | None = None,
        role_key: str | None = None,
    ) -> tuple[EvidenceNode, ...]:
        raise NotImplementedError

    def find_edges(
        self,
        compile_id: str,
        edge_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[EvidenceEdge, ...]:
        raise NotImplementedError

    def find_comparisons(
        self,
        analysis_id: str,
        relation_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[ComparisonRecord, ...]:
        raise NotImplementedError

    def subgraph(
        self,
        roots: Iterable[str],
        edge_kinds: frozenset[str],
        max_depth: int,
    ) -> AdapterResult:
        raise NotImplementedError


class EvidenceStore(EvidenceSink, EvidenceQuery, Protocol):
    """Storage-neutral interface used by orchestration and inference."""
```

Implement atomic batch validation before insertion, same-ID/same-content no-op behavior, collision rejection, endpoint validation, canonical tuple ordering, and deterministic breadth-first `subgraph`. Use the exact sort keys from the design spec.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_store.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/pyproject.toml tools/melee-agent/src/mwcc_debug/causal_diff tools/melee-agent/tests/test_causal_diff_store.py
git commit -m "feat: add causal evidence store"
```

---

### Task 2: Bundle Schema, Digests, and Capability Gate

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/bundles.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/models.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/__init__.py`
- Create: `tools/melee-agent/tests/test_causal_diff_bundles.py`

**Interfaces:**
- Consumes: `canonical_bytes`, `stable_id`.
- Produces: `CORE_BACKEND_CAPABILITIES`, `ArtifactRef`, `BackendArtifactRef`, `CompileManifest`, `FrontierBundleManifest`, `ValidatedBundle`, `load_bundle`, `validate_bundle_pair`, and `validate_capability_union`.

- [ ] **Step 1: Write failing manifest and compatibility tests**

```python
def test_pair_accepts_distinct_sources_in_shared_environment(tmp_path: Path) -> None:
    paired = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")
    direct = write_valid_bundle(tmp_path / "direct", label="direct", source="direct")
    first = load_bundle(paired, cli_label="paired", function="fn_test")
    second = load_bundle(direct, cli_label="direct", function="fn_test")
    validate_bundle_pair(first, second)
    assert first.compile_id != second.compile_id
    assert first.manifest.compile.environment_digest == second.manifest.compile.environment_digest


def test_pair_rejects_expected_assembly_mismatch(tmp_path: Path) -> None:
    paired = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    direct_path = write_valid_bundle(tmp_path / "direct", label="direct", source="direct")
    payload = json.loads(direct_path.read_text())
    payload["compile"]["expected_assembly_digest"] = "9" * 64
    direct_path.write_text(json.dumps(payload))
    direct = load_bundle(direct_path, cli_label="direct", function="fn_test")
    with pytest.raises(BundleInputError, match="expected assembly"):
        validate_bundle_pair(paired, direct)


def test_capability_claim_must_be_verified(tmp_path: Path) -> None:
    bundle = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    with pytest.raises(BundleInputError, match="missing backend capabilities"):
        validate_capability_union(bundle, frozenset({"allocator-decisions"}))
```

The fixture helper must create source, checkdiff, PCode, inspector, and frame files, compute their SHA-256 digests, compute `compile.id` from function/compiler/target/flags/environment/source, and write a valid JSON manifest. Add parameterized negative tests for a missing artifact, bad digest, CLI/manifest label mismatch, unknown capability, missing `target_build`, bad compile ID, and incompatible flags/environment/compiler.

- [ ] **Step 2: Verify failure before implementation**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_bundles.py -q
```

Expected: import fails for `src.mwcc_debug.causal_diff.bundles`.

- [ ] **Step 3: Implement strict Pydantic manifest models**

```python
CORE_BACKEND_CAPABILITIES = frozenset(
    {
        "pcode-occurrences",
        "virtual-use-def",
        "virtual-to-allocator-node",
        "allocator-decisions",
        "interference-edges",
    }
)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: str


class BackendArtifactRef(ArtifactRef):
    format: Literal["mwcc-debug-pcdump", "backend-trace.v1"]
    capabilities: tuple[str, ...]


class CompileManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    compiler: str
    target_build: Literal["GALE01"]
    flags_digest: str
    environment_digest: str
    source_digest: str
    expected_assembly_digest: str


class ArtifactsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: ArtifactRef
    checkdiff: ArtifactRef
    backend: tuple[BackendArtifactRef, ...]
    inspector: ArtifactRef
    frame_report: ArtifactRef | None = None


class FrontierBundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["causal-frontier-bundle.v1"]
    label: str
    function: str
    compile: CompileManifest
    artifacts: ArtifactsManifest
    producer_versions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    manifest_path: Path
    manifest: FrontierBundleManifest
    label: str
    compile_id: str
    artifact_paths: Mapping[str, Path]

    def read_text(self, artifact_name: str) -> str:
        return self.artifact_paths[artifact_name].read_text(encoding="utf-8")
```

Reject non-hex or non-64-character digests. Resolve artifact paths relative to the manifest. Recompute all file hashes, verify `source_digest`, and recompute the compile ID with RFC 8785. `validate_bundle_pair` sorts by label, requires two distinct labels/compile IDs, and compares expected/compiler/target/flags/environment fields.

- [ ] **Step 4: Implement the post-adapter capability gate**

`validate_capability_union(bundle, verified)` must reject any manifest claim outside the adapter's verified set and reject a verified union missing any core capability. Unknown declared capability names fail manifest validation.

- [ ] **Step 5: Run focused tests and commit**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_bundles.py tests/test_causal_diff_store.py -q
cd ../..
git add tools/melee-agent/src/mwcc_debug/causal_diff tools/melee-agent/tests/test_causal_diff_bundles.py
git commit -m "feat: validate causal frontier bundles"
```

Expected: all tests pass and the commit succeeds.

---

### Task 3: Semantic mwcc-inspect Parser and Adapter

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/inspect_parser.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/inspect_adapter.py`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/inspect/paired_excerpt.txt`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/inspect/unknown_syntax.txt`
- Create: `tools/melee-agent/tests/test_causal_diff_inspect.py`

**Interfaces:**
- Consumes: `ValidatedBundle`, evidence record factories.
- Produces: `InspectObjObject`, `InspectENode`, `InspectStatement`, `InspectFunction`, `parse_inspect_function`, and `adapt_inspector`.

- [ ] **Step 1: Add a minimized real inspector fixture and failing parser tests**

Use the real `mnDiagram_DrawFighterHeaders` section from `/Users/mike/.codex/worktrees/eeff/melee/build/mwcc_inspect/fighter-keeper.txt`, retaining the nested `EASS`/`ECOMMA` tree at source lines 18882–18910 and both local-order tables. The fixture must include the `fighter_id` ObjObject, synthetic `@1862` and `@1863` ObjObjects, statement raw text, addresses, data types, and source line markers.

```python
def test_parse_nested_assignment_and_objobject_ownership() -> None:
    text = FIXTURE.read_text()
    fn = parse_inspect_function(text, "mnDiagram_DrawFighterHeaders")
    assert fn is not None
    assignment = next(node for node in fn.enodes if node.opcode == "EASS" and "fighter_id" in node.expression)
    referenced = {fn.objobjects[address].name for address in assignment.referenced_object_addresses}
    assert referenced == {"fighter_id", "@1863"}
    assert fn.objobjects["0x00FEC850"].first_appearance_order == 19
    assert fn.objobjects["0x00FEC850"].address_order == 36
    assert assignment.raw_start < assignment.raw_end


def test_unknown_inspector_line_is_warning_not_edge() -> None:
    fn = parse_inspect_function(UNKNOWN_FIXTURE.read_text(), "fn_test")
    assert fn is not None
    assert fn.warnings == ("line 6: unsupported inspector syntax: [ENEWFORM] value",)
    assert all(node.opcode != "ENEWFORM" for node in fn.enodes)
```

- [ ] **Step 2: Confirm tests fail on the snapshot-only parser**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_inspect.py -q
```

Expected: import fails because `parse_inspect_function` is absent.

- [ ] **Step 3: Implement the indentation-preserving semantic parser**

Add these immutable types to `inspect_parser.py`:

```python
@dataclass(frozen=True, slots=True)
class InspectObjObject:
    address: str
    name: str
    data_type: str
    type_text: str
    first_appearance_order: int | None
    address_order: int | None
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectENode:
    node_id: str
    opcode: str
    expression: str
    depth: int
    parent_id: str | None
    referenced_object_addresses: tuple[str, ...]
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectStatement:
    statement_id: str
    source_line: int | None
    expression: str
    root_enode_id: str | None
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class InspectFunction:
    name: str
    statements: tuple[InspectStatement, ...]
    enodes: tuple[InspectENode, ...]
    objobjects: Mapping[str, InspectObjObject]
    warnings: tuple[str, ...]
```

Slice with the existing function-boundary logic. Parse statement headers with `^:(?P<meta>-?\d+)\s+(?P<expression>.+)$`, ENodes with indentation plus `\[(?P<opcode>E[A-Z0-9_]+)\]`, and explicit ObjObject lines with `-> ObjObject @ (?P<address>0x[0-9A-Fa-f]+):`. Maintain an indentation stack to assign parents. Attach each ObjObject line to its nearest preceding `EOBJREF`, then propagate referenced addresses to ancestor ENodes. Merge first-appearance and address-order tables by address. Preserve byte offsets, not only line numbers.

- [ ] **Step 4: Adapt semantic records without confidence laundering**

`adapt_inspector(bundle)` must emit observed statement/ENode/ObjObject nodes plus `statement-has-enode`, `enode-child`, and `enode-references-object` edges. Unsupported syntax becomes `AdapterResult.warnings`; it does not create nodes or edges. Explicit inspector structure has producer and adapter confidence `OBSERVED`; any inferred ancestor aggregation is `DERIVED_UNIQUE`.

- [ ] **Step 5: Run parser regressions and commit**

```bash
cd tools/melee-agent
python -m pytest tests/test_mwcc_debug_inspect_parser.py tests/test_causal_diff_inspect.py -q
cd ../..
git add tools/melee-agent/src/mwcc_debug/inspect_parser.py tools/melee-agent/src/mwcc_debug/causal_diff/inspect_adapter.py tools/melee-agent/tests/fixtures/causal_diff/inspect tools/melee-agent/tests/test_causal_diff_inspect.py
git commit -m "feat: parse semantic mwcc inspect evidence"
```

Expected: existing snapshot tests and new semantic tests pass.

---

### Task 4: Checkdiff and Backend Evidence Adapters

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/asm_adapter.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py`
- Create: `tools/melee-agent/tests/test_causal_diff_backend_adapters.py`

**Interfaces:**
- Consumes: `ValidatedBundle`, `facts_from_pcdump`, `facts_from_backend_trace`, `parse_pcdump`, `find_virtual_to_ig`, and `role_descriptor.Compile`.
- Produces: `CheckdiffInstruction`, `CheckdiffEvidence`, `BackendEvidence`, `adapt_checkdiff`, and `adapt_backends`.

- [ ] **Step 1: Write failing checkdiff/backend adapter tests**

```python
def test_checkdiff_adapter_indexes_retail_offsets() -> None:
    evidence = adapt_checkdiff(validated_bundle("direct"))
    row = evidence.rows_by_offset[0x234]
    assert row.expected.opcode == "addi"
    assert row.expected.regs == (("r", 22), ("r", 21))
    assert row.current.regs == (("r", 20), ("r", 19))


def test_backend_adapter_verifies_all_pcdump_capabilities() -> None:
    evidence = adapt_backends(validated_bundle("direct"))
    assert evidence.verified_capabilities == CORE_BACKEND_CAPABILITIES
    node = next(node for node in evidence.result.nodes if node.kind == "allocator-node" and node.attributes["ig_id"] == 66)
    assert node.attributes["assigned_phys"] == 21
    assert evidence.role_compile.name == "mnDiagram_DrawFighterHeaders"


def test_allocator_only_trace_fails_core_capability_gate() -> None:
    bundle = validated_bundle("allocator-only")
    evidence = adapt_backends(bundle)
    with pytest.raises(BundleInputError, match="pcode-occurrences"):
        validate_capability_union(bundle, evidence.verified_capabilities)
```

- [ ] **Step 2: Run tests and verify missing adapters**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_backend_adapters.py -q
```

Expected: import fails for `asm_adapter` and `backend_adapter`.

- [ ] **Step 3: Implement checkdiff parsing and digest verification**

```python
@dataclass(frozen=True, slots=True)
class CheckdiffInstruction:
    offset: int
    opcode: str
    operands: str
    regs: tuple[tuple[str, int], ...]
    raw: str


@dataclass(frozen=True, slots=True)
class CheckdiffRow:
    offset: int
    expected: CheckdiffInstruction
    current: CheckdiffInstruction


@dataclass(frozen=True, slots=True)
class CheckdiffEvidence:
    result: AdapterResult
    rows_by_offset: Mapping[int, CheckdiffRow]
    stack_slot_localizer: Mapping[str, object] | None
    target_assembly: tuple[str, ...]
    current_assembly: tuple[str, ...]
    expected_assembly_digest: str
```

Parse `+NNN:` lines, ignore relocation-only rows for instruction pairing, require unique expected/current instruction rows per byte offset, and compute the expected digest from UTF-8 `"\n".join(target_asm).rstrip() + "\n"`. Reject a mismatch with the manifest. Emit compile-local retail and candidate instruction nodes plus `aligns-to-retail` edges backed by the checkdiff rows.

- [ ] **Step 4: Implement backend normalization by reusing existing facts**

```python
@dataclass(frozen=True, slots=True)
class BackendEvidence:
    result: AdapterResult
    pcdump_text: str
    role_compile: role_descriptor.Compile
    nodes_by_class_ig: Mapping[tuple[int, int], str]
    nodes_by_virtual: Mapping[tuple[str, int], str]
```

For `mwcc-debug-pcdump`, call `facts_from_pcdump`, `parse_pcdump`, `find_virtual_to_ig`, and `role_descriptor.Compile.from_text`. Emit PCode occurrence, virtual-register, allocator-node, and allocator-decision nodes; emit use/def, virtual-to-allocator, decision, interference, and coalesce edges. For `backend-trace.v1`, call `facts_from_backend_trace` and emit only facts actually present. The verified capability union comes from parsed structure, never the manifest claim. Preserve each producer fact's confidence; missing producer confidence becomes `HEURISTIC` unless the versioned raw parser contract designates the field observed.

- [ ] **Step 5: Run adapter and existing allocator tests**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_backend_adapters.py tests/test_copy_trace.py tests/test_lifetime_pressure_explorer.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/mwcc_debug/causal_diff/asm_adapter.py tools/melee-agent/src/mwcc_debug/causal_diff/backend_adapter.py tools/melee-agent/tests/test_causal_diff_backend_adapters.py
git commit -m "feat: normalize causal backend evidence"
```

---

### Task 5: Frame, Source, and Within-Compile Ownership Joins

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/frame_adapter.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/source_adapter.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/graph.py`
- Create: `tools/melee-agent/tests/test_causal_diff_ownership.py`

**Interfaces:**
- Consumes: `analyze_frame_reservations`, `explain_stack_slot_localizer`, semantic inspector records, source text, and backend evidence.
- Produces: `FrameEvidence`, `SourceEvidence`, `FrontierGraph`, `adapt_frame`, `adapt_source`, and `build_frontier_graph`.

- [ ] **Step 1: Write failing confidence and ownership-join tests**

```python
def test_frame_report_preserves_derived_confidence() -> None:
    evidence = adapt_frame(bundle_with_derived_frame_report(), checkdiff(), backend())
    stack = next(node for node in evidence.result.nodes if node.kind == "stack-object")
    assert stack.producer_confidence is Confidence.DERIVED_UNIQUE
    assert stack.confidence is Confidence.DERIVED_UNIQUE


def test_unique_inspector_to_backend_join_is_proof_capable() -> None:
    graph = build_frontier_graph(
        bundle(), InMemoryEvidenceStore(), checkdiff(), backend(), inspector(), frame(), source()
    )
    edges = graph.store.find_edges(bundle().compile_id, edge_kind="lowers-to")
    fighter_edge = next(edge for edge in edges if edge.attributes["consumer"] == "HSD_JObjReqAnimAll")
    assert fighter_edge.confidence is Confidence.DERIVED_UNIQUE
    assert fighter_edge.provenance.input_record_ids


def test_name_only_stack_join_remains_heuristic() -> None:
    graph = build_frontier_graph(
        bundle(),
        InMemoryEvidenceStore(),
        checkdiff(),
        backend(),
        inspector(),
        ambiguous_frame(),
        source(),
    )
    edges = graph.store.find_edges(bundle().compile_id, edge_kind="materializes-as-stack-object")
    assert edges
    assert all(edge.confidence is Confidence.HEURISTIC for edge in edges)
```

- [ ] **Step 2: Verify failure before the adapters exist**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_ownership.py -q
```

Expected: imports fail for `frame_adapter`, `source_adapter`, and `graph`.

- [ ] **Step 3: Implement frame and stack-slot evidence adaptation**

```python
@dataclass(frozen=True, slots=True)
class FrameEvidence:
    result: AdapterResult
    expected_stack_roles: Mapping[str, tuple[int, int]]
    current_stack_nodes: Mapping[str, str]


def adapt_frame(
    bundle: ValidatedBundle,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
) -> FrameEvidence:
    if bundle.manifest.artifacts.frame_report is not None:
        report = parse_supplied_frame_report(bundle.read_text("frame_report"))
    else:
        report = derive_frame_report(
            pcdump_text=backend.pcdump_text,
            source_text=bundle.read_text("source"),
            target_assembly=checkdiff.target_assembly,
            current_assembly=checkdiff.current_assembly,
            stack_slot_localizer=checkdiff.stack_slot_localizer,
        )
    return frame_evidence_from_report(bundle, report)
```

Implement `parse_supplied_frame_report`, `derive_frame_report`, and `frame_evidence_from_report` in the same module. `derive_frame_report` calls `analyze_frame_reservations` with the already loaded PCode, source, target assembly, and current assembly, then feeds `classification.stack_slot_localizer` to `explain_stack_slot_localizer`. Emit every `frame_allocation_trace.objects[]` entry as a stack-object node. Map producer statuses to confidence explicitly: raw emitted offsets are observed; computed symbolic ownership is derived-unique; source guesses and ordinal-only ownership are heuristic. These functions must contain no subprocess call or file write.

- [ ] **Step 4: Implement source and direct-inline scope evidence**

```python
@dataclass(frozen=True, slots=True)
class SourceEvidence:
    result: AdapterResult
    expressions_by_signature: Mapping[str, tuple[str, ...]]
    inline_scopes_by_callee: Mapping[str, tuple[str, ...]]
```

Use `source_patch.find_function_definitions` and the existing tree-sitter C helpers to collect expressions from the target function and one level of directly called `static inline` functions. Build normalized signatures from operator/node type, referenced identifiers, called functions, constants, and enclosing scope path. Exact source span plus unique signature is derived-unique; multiple matching spans are heuristic and all candidates remain present.

- [ ] **Step 5: Implement joins with explicit proof rules**

```python
@dataclass(frozen=True, slots=True)
class FrontierGraph:
    bundle: ValidatedBundle
    store: EvidenceStore
    checkdiff: CheckdiffEvidence
    backend: BackendEvidence
    inspector: InspectEvidence
    frame: FrameEvidence
    source: SourceEvidence
    warnings: tuple[str, ...]


def build_frontier_graph(
    bundle: ValidatedBundle,
    store: EvidenceStore,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
    inspector: InspectEvidence,
    frame: FrameEvidence,
    source: SourceEvidence,
) -> FrontierGraph:
    add_adapter_results_atomically(
        store,
        (checkdiff.result, backend.result, inspector.result, frame.result, source.result),
    )
    join_result = derive_within_compile_joins(
        bundle, checkdiff, backend, inspector, frame, source
    )
    store.add_nodes(join_result.nodes)
    store.add_edges(join_result.edges)
    return FrontierGraph(
        bundle=bundle,
        store=store,
        checkdiff=checkdiff,
        backend=backend,
        inspector=inspector,
        frame=frame,
        source=source,
        warnings=canonical_warnings(
            checkdiff, backend, inspector, frame, source, join_result
        ),
    )
```

`build_frontier_graph` ingests every adapter result, then creates:

- `expression-represents-enode` when normalized operator tree, identifiers, consumer call, type, and scope yield exactly one source span;
- `lowers-to` when the inspector expression and one PCode def-use chain share a unique normalized operation/consumer/type/order signature;
- `materializes-as-stack-object` when symbolic name plus defining expression/consumer/stack access identify exactly one object;
- heuristic edges for finite ambiguous candidates, never for missing segments.

Every derived edge lists its input record IDs and uses the weakest input confidence.

- [ ] **Step 6: Run frame/source regressions and commit**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_ownership.py tests/test_stack_slot_bridge.py tests/test_frame_reservations.py -q
cd ../..
git add tools/melee-agent/src/mwcc_debug/causal_diff/frame_adapter.py tools/melee-agent/src/mwcc_debug/causal_diff/source_adapter.py tools/melee-agent/src/mwcc_debug/causal_diff/graph.py tools/melee-agent/tests/test_causal_diff_ownership.py
git commit -m "feat: join causal source and stack ownership"
```

Expected: all tests pass.

---

### Task 6: Anchor Alignment, Effect Derivation, and Graph Differencing

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/effects.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/differ.py`
- Create: `tools/melee-agent/tests/test_causal_diff_alignment.py`

**Interfaces:**
- Consumes: two `FrontierGraph` values and existing role descriptors/matchers.
- Produces: `OperandRole`, `AnchorAlignment`, `AllocatorEffect`, `StackEffect`, `EffectPair`, `align_anchor`, `build_role_comparisons`, `derive_effects`, and `diff_frontiers`.

- [ ] **Step 1: Write failing multi-operand and reused-register tests**

```python
def test_anchor_0234_derives_def_and_use_roles() -> None:
    alignment = align_anchor(graphs(), retail_offset=0x234, assertions=())
    assert [(role.kind, role.position, role.expected_phys) for role in alignment.operand_roles] == [
        ("def", 0, 22),
        ("use", 0, 21),
    ]


def test_role_matcher_does_not_select_later_reused_r22_node() -> None:
    alignment = align_anchor(reused_register_graphs(), retail_offset=0x234, assertions=())
    row_def = alignment.by_operand["def:0"]
    assert row_def.right.attributes["first_def_signature"] == "addi r#,r#,0"
    assert row_def.right.attributes["ig_id"] == 66
    assert row_def.right.attributes["ig_id"] != 58


def test_effect_direction_is_independent_of_cli_order() -> None:
    forward = derive_effects(align_anchor(graphs("paired", "direct"), 0x234, ()), graphs())
    reverse = derive_effects(align_anchor(graphs("direct", "paired"), 0x234, ()), graphs())
    assert forward == reverse
    assert forward.allocator_effects[0].direction == "first-exact-second-mismatch"


def test_unresolved_operand_does_not_drop_resolved_operand() -> None:
    result = derive_effects(alignment_with_missing_use(), graphs())
    assert [effect.operand_key for effect in result.allocator_effects] == ["def:0"]
    assert result.abstentions[0].operand_key == "use:0"
```

- [ ] **Step 2: Run tests and verify missing alignment layer**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_alignment.py -q
```

Expected: imports fail for `alignment`, `effects`, and `differ`.

- [ ] **Step 3: Implement instruction and role alignment**

```python
@dataclass(frozen=True, slots=True)
class OperandRole:
    key: str
    kind: Literal["def", "use"]
    position: int
    register_kind: Literal["r", "f"]
    expected_phys: int


@dataclass(frozen=True, slots=True)
class AnchorAlignment:
    analysis_id: str
    retail_offset: int
    operand_roles: tuple[OperandRole, ...]
    by_operand: Mapping[str, RolePair]
    comparisons: tuple[ComparisonRecord, ...]
    abstentions: tuple[EffectAbstention, ...]
```

`RolePair` contains the two uniquely matched compile-local allocator nodes plus their analysis-scoped comparison record. `EffectAbstention` contains `operand_key`, a stable reason enum, missing capability/record IDs, and follow-up commands. Define both in `alignment.py` before `AnchorAlignment`; do not use untyped dictionaries for either contract.

Use opcode semantics to exclude fixed/non-allocatable registers and to order definitions before uses. Align checkdiff rows uniquely by offset and normalized opcode neighborhood. Build descriptors with `role_descriptor.build_descriptors`, match both directions with `role_matcher.match_roles`, and require the same round-trip rule as `role_reanchor._confirm_round_trip`. Physical register reuse is diagnostic only. Parse assertions as `LABEL:OPERAND=SPEC`; accepted assertions create heuristic comparison records and cap later verdicts at `candidate-cause`.

- [ ] **Step 4: Implement deterministic effects and deltas**

```python
@dataclass(frozen=True, slots=True)
class AllocatorEffect:
    effect_id: str
    operand_key: str
    expected_phys: int
    first_label: str
    first_phys: int | None
    second_label: str
    second_phys: int | None
    direction: str
    role_correspondence: RolePair


@dataclass(frozen=True, slots=True)
class StackEffect:
    effect_id: str
    role_key: str
    expected_offset: int | None
    first_label: str
    first_offset: int | None
    second_label: str
    second_offset: int | None
    direction: str
    owner_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EffectPair:
    pair_id: str
    allocator: AllocatorEffect
    stack: StackEffect
    allocator_exact_stack_mismatch_label: str
    allocator_mismatch_stack_exact_label: str


@dataclass(frozen=True, slots=True)
class DerivedEffects:
    allocator_effects: tuple[AllocatorEffect, ...]
    stack_effects: tuple[StackEffect, ...]
    pairs: tuple[EffectPair, ...]
    abstentions: tuple[EffectAbstention, ...]
```

Follow the spec's five direction enums, label sorting, tied-role merging, expected stack role rules, absent-object mismatch rule, and canonical ordering. Create eligible pairs only when the same frontier is allocator-exact/stack-mismatched and the other is allocator-mismatched/stack-exact. `diff_frontiers` emits analysis-scoped node/edge added, removed, and changed records; it never adds cross-compile edges.

- [ ] **Step 5: Run role/alignment regressions and commit**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_alignment.py tests/test_role_reanchor.py tests/test_first_divergence.py -q
cd ../..
git add tools/melee-agent/src/mwcc_debug/causal_diff/alignment.py tools/melee-agent/src/mwcc_debug/causal_diff/effects.py tools/melee-agent/src/mwcc_debug/causal_diff/differ.py tools/melee-agent/tests/test_causal_diff_alignment.py
git commit -m "feat: derive causal frontier effects"
```

Expected: all tests pass, including the IG66-versus-IG58 regression.

---

### Task 7: Strict Inference and Stable Reporting

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/inference.py`
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/render.py`
- Create: `tools/melee-agent/tests/test_causal_diff_inference.py`

**Interfaces:**
- Consumes: `DerivedEffects`, comparison records, and `EvidenceQuery`.
- Produces: `VerdictStatus`, `CausalVerdict`, `AnalysisStatus`, `CausalDiffReport`, `infer_pair`, `build_report`, `exit_code_for_report`, `render_text`, and `render_json`.

- [ ] **Step 1: Encode the decision table as failing parameterized tests**

```python
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (proof_complete_unique(), VerdictStatus.CAUSES),
        (complete_heuristic_path(), VerdictStatus.CANDIDATE_CAUSE),
        (complete_two_owner_paths(), VerdictStatus.CANDIDATE_CAUSE),
        (complete_no_shared_path(), VerdictStatus.NO_CAUSAL_DIFFERENCE),
        (missing_anchor_identity(), VerdictStatus.ABSTAIN),
        (truncated_path(), VerdictStatus.ABSTAIN),
        (contradictory_ownership(), VerdictStatus.ABSTAIN),
        (expert_asserted_complete_path(), VerdictStatus.CANDIDATE_CAUSE),
    ],
)
def test_normative_verdict_table(case: InferenceCase, expected: VerdictStatus) -> None:
    assert infer_pair(case.pair, case.query, case.comparisons).status is expected


def test_exit_aggregation_keeps_partial_success_at_zero() -> None:
    report = report_with(VerdictStatus.CAUSES, VerdictStatus.ABSTAIN)
    assert report.analysis_status is AnalysisStatus.PARTIAL
    assert exit_code_for_report(report) == 0


def test_all_abstentions_exit_three() -> None:
    report = report_with(VerdictStatus.ABSTAIN, VerdictStatus.ABSTAIN)
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    assert exit_code_for_report(report) == 3
```

- [ ] **Step 2: Verify the inference module is absent**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_inference.py -q
```

Expected: import failure for `inference`.

- [ ] **Step 3: Implement proof-path enumeration and verdict gates**

`infer_pair` must enumerate all owner-to-allocator and owner-to-stack paths within the already bounded subgraph. It returns:

- `causes` only for one changed shared owner and proof-capable paths;
- `candidate-cause` for complete finite alternatives with heuristic edges, multiple owners, or an expert assertion;
- `no-causal-difference` when complete graphs contain no changed shared mediator;
- `abstain` for identity failure, missing segments, traversal truncation, contradiction, digest/environment invalidity, or non-enumerable alternatives.

Every verdict contains effect IDs, cause record IDs, shortest canonical proof paths, rejected alternatives, failed gates, operational-causality scope text, and exact read-only follow-up commands.

- [ ] **Step 4: Implement report and rendering contracts**

```python
class VerdictStatus(StrEnum):
    CAUSES = "causes"
    CANDIDATE_CAUSE = "candidate-cause"
    NO_CAUSAL_DIFFERENCE = "no-causal-difference"
    ABSTAIN = "abstain"


class AnalysisStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class AppliedRule:
    rule_id: str
    input_record_ids: tuple[str, ...]
    output_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CausalVerdict:
    verdict_id: str
    status: VerdictStatus
    pair_id: str
    cause: EvidenceNode | None
    proof_paths: tuple[tuple[str, ...], ...]
    rejected_alternatives: tuple[str, ...]
    failed_gates: tuple[str, ...]
    allocator_delta: Mapping[str, object]
    stack_delta: Mapping[str, object]
    recommendation: str
    follow_up_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CausalDiffReport:
    schema_version: Literal["causal-diff-report.v1"]
    analysis_id: str
    analysis_status: AnalysisStatus
    function: str
    effects: DerivedEffects
    verdicts: tuple[CausalVerdict, ...]
    comparisons: tuple[ComparisonRecord, ...]
    applied_rules: tuple[AppliedRule, ...]
    missing_evidence: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return report_to_canonical_dict(self)


def render_json(report: CausalDiffReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


def render_text(report: CausalDiffReport) -> str:
    lines = [f"causal-diff - {report.function}", f"status: {report.analysis_status.value}"]
    for verdict in report.verdicts:
        lines.extend(render_verdict_lines(verdict))
    lines.extend(render_missing_and_warning_lines(report))
    return "\n".join(lines) + "\n"
```

The JSON dictionary follows `causal-diff-report.v1` and canonically sorts all semantic collections before pretty printing. Human output leads with verdict, cause, shortest path, allocator/stack deltas, failed gates, and commands; it does not dump the full graph.

- [ ] **Step 5: Run inference tests and commit**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_inference.py -q
cd ../..
git add tools/melee-agent/src/mwcc_debug/causal_diff/inference.py tools/melee-agent/src/mwcc_debug/causal_diff/render.py tools/melee-agent/tests/test_causal_diff_inference.py
git commit -m "feat: infer strict causal verdicts"
```

Expected: all decision-table and exit-code tests pass.

---

### Task 8: Read-Only Orchestration and CLI Surface

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/causal_diff/commands.py`
- Modify: `tools/melee-agent/src/mwcc_debug/causal_diff/__init__.py`
- Modify: `tools/melee-agent/src/cli/debug/inspect.py`
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Create: `tools/melee-agent/tests/test_causal_diff_cli.py`
- Create: `tools/melee-agent/tests/golden/debug_cli_help/debug__inspect__causal-diff.txt`

**Interfaces:**
- Consumes: every prior package interface and a caller-supplied `EvidenceStore` factory for storage-neutral execution.
- Produces: `CausalDiffOptions`, `run_causal_diff`, CLI parsers, and the public Typer command.

- [ ] **Step 1: Write failing CLI and no-side-effect tests**

```python
def test_causal_diff_json_command(tmp_path: Path) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    result = runner.invoke(
        app,
        [
            "debug", "inspect", "causal-diff",
            "-f", "fn_test",
            "--frontier", f"paired={paired}",
            "--frontier", f"direct={direct}",
            "--retail-offset", "0x234",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "causal-diff-report.v1"
    assert payload["analysis_status"] == "complete"


def test_causal_diff_never_spawns_or_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: pytest.fail("write forbidden"))
    report = run_causal_diff(options_for(tmp_path))
    assert report.function == "fn_test"


def test_input_error_is_exit_two(tmp_path: Path) -> None:
    result = runner.invoke(app, invalid_digest_args(tmp_path))
    assert result.exit_code == 2
    assert "digest mismatch" in result.stderr
```

Add CLI cases for exactly-two-frontier enforcement, duplicate labels, label regex/mismatch, invalid offset/depth, assertion syntax `paired:def:0=gpr:66`, exit `3` for all-abstain, and exit `0` for partial results.

- [ ] **Step 2: Confirm the command is absent**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_cli.py -q
```

Expected: Typer reports `No such command 'causal-diff'`.

- [ ] **Step 3: Implement pure orchestration**

```python
@dataclass(frozen=True, slots=True)
class CausalDiffOptions:
    function: str
    frontiers: tuple[tuple[str, Path], tuple[str, Path]]
    retail_offset: int
    assertions: tuple[str, ...] = ()
    evidence_depth: int = 4


def run_causal_diff(
    options: CausalDiffOptions,
    *,
    store_factory: Callable[[], EvidenceStore] = InMemoryEvidenceStore,
) -> CausalDiffReport:
    bundles = load_and_validate_pair(options)
    store = store_factory()
    graphs: list[FrontierGraph] = []
    for bundle in bundles:
        checkdiff = adapt_checkdiff(bundle)
        backend = adapt_backends(bundle)
        inspector = adapt_inspector(bundle)
        frame = adapt_frame(bundle, checkdiff, backend)
        source = adapt_source(bundle)
        validate_capability_union(
            bundle,
            backend.result.verified_capabilities | inspector.result.verified_capabilities,
        )
        graphs.append(
            build_frontier_graph(
                bundle,
                store,
                checkdiff,
                backend,
                inspector,
                frame,
                source,
            )
        )
    graph_pair = (graphs[0], graphs[1])
    alignment = align_anchor(graph_pair, options.retail_offset, options.assertions)
    comparisons = build_role_comparisons(alignment, graph_pair)
    effects = derive_effects(alignment, graph_pair)
    deltas = diff_frontiers(graph_pair, comparisons)
    store.add_comparisons(comparisons + deltas)
    return build_report(graph_pair, effects, comparisons + deltas)
```

Every adapter invocation above parses only supplied artifacts; none compiles or writes. Validate the capability union before `build_frontier_graph` inserts any adapter result. Keep command orchestration in `commands.py`, not the large Typer module.

- [ ] **Step 4: Register the Typer command and capability alias**

Add `@inspect_app.command(name="causal-diff")` with exact options from the spec. Parse two `LABEL=MANIFEST` values, `int(value, 0)` retail offset, depth range `1..8`, and operand-scoped assertions. Print `render_json` or `render_text`, then raise `typer.Exit(exit_code_for_report(report))` only for nonzero status. Catch `BundleInputError` and other declared input exceptions as exit `2` without a causal report.

Add `debug inspect causal-diff` to the `debug registers`, `register allocation`, `stack home ownership`, and `compiler provenance` task aliases in `src/cli/capabilities.py`.

- [ ] **Step 5: Regenerate the intentional help golden and run CLI tests**

```bash
cd tools/melee-agent
MELEE_REGEN_GOLDEN=1 python -m pytest tests/test_debug_cli_help_golden.py -q
python -m pytest tests/test_causal_diff_cli.py tests/test_debug_cli_help_golden.py tests/test_capabilities.py -q
```

Expected: the new `debug__inspect__causal-diff.txt` golden exists and all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/mwcc_debug/causal_diff tools/melee-agent/src/cli/debug/inspect.py tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_causal_diff_cli.py tools/melee-agent/tests/golden/debug_cli_help
git commit -m "feat: expose causal diff command"
```

---

### Task 9: DrawFighterHeaders Pilot Fixture and End-to-End Proof

**Files:**
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/paired/source.c`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/paired/checkdiff.json`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/paired/pcdump.txt`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/paired/inspect.txt`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/paired/frame.json`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/direct/source.c`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/direct/checkdiff.json`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/direct/pcdump.txt`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/direct/inspect.txt`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/direct/frame.json`
- Create: `tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers/metadata.json`
- Create: `tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py`

**Interfaces:**
- Consumes: public `run_causal_diff`, `InMemoryEvidenceStore`, and a test `RecordingPersistentStore` implementing the same protocols.
- Produces: checked-in minimized real artifacts and the required generic pilot proof.

- [ ] **Step 1: Build minimized fixtures from the preserved campaign artifacts**

Use these sources of truth:

- Paired source: `git -C /Users/mike/.codex/worktrees/eeff/melee show f70dfdafa:src/melee/mn/mndiagram.c`.
- Direct source: `git -C /Users/mike/.codex/worktrees/eeff/melee show 871eec422:src/melee/mn/mndiagram.c`.
- Paired PCode: `/Users/mike/.codex/worktrees/eeff/melee/build/mwcc_debug_cache/melee/mn/mndiagram-fighterheaders-inline-helper.txt`.
- Direct PCode: `/Users/mike/.codex/worktrees/eeff/melee/build/mwcc_debug_cache/melee/mn/mndiagram-fighterheaders-hybrid-col-direct.txt`.
- Paired inspector: `/Users/mike/.codex/worktrees/eeff/melee/build/mwcc_inspect/fighter-keeper.txt`.
- Direct inspector: `/Users/mike/.codex/worktrees/eeff/melee/build/mwcc_inspect/mndiagram.txt`.
- Retail/checkdiff truth: `tools/checkdiff.py mnDiagram_DrawFighterHeaders --format json --no-build` in the `eeff` worktree.

Use `tools/melee-agent/scripts/slice_pcdump_function.py` for PCode. Copy only the target function's inspector section and direct inline source definitions through the target function. Preserve the exact compiler syntax and provenance line metadata. The checkdiff fixture must include retail/current rows around `+0x230..+0x25c`, row-child stack rows around `+0x2f4..+0x308`, and a stack localizer showing retail/direct `0x44` versus paired `0x48`. `metadata.json` stores compiler `mwcc_233_163n`, target `GALE01`, flags/environment digests, source commits, original paths, and anchor `564` (`0x234`). Tests create temporary manifests with computed fixture digests.

- [ ] **Step 2: Write the failing end-to-end acceptance test**

```python
def test_draw_fighter_headers_proves_shared_cause(tmp_path: Path) -> None:
    paired, direct = materialize_manifests(tmp_path)
    report = run_causal_diff(
        CausalDiffOptions(
            function="mnDiagram_DrawFighterHeaders",
            frontiers=(("paired", paired), ("direct", direct)),
            retail_offset=0x234,
        )
    )
    assert report.analysis_status is AnalysisStatus.COMPLETE
    row = next(
        effect for effect in report.effects.allocator_effects if effect.operand_key == "def:0"
    )
    assert row.expected_phys == 22
    assert {row.first_phys, row.second_phys} == {20, 22}
    verdict = next(item for item in report.verdicts if item.status is VerdictStatus.CAUSES)
    assert verdict.cause.attributes["source_name"] == "fighter_id"
    assert verdict.allocator_delta["expected_phys"] == 22
    assert verdict.stack_delta == {"expected_offset": 0x44, "paired_offset": 0x48, "direct_offset": 0x44}
    assert "preserve" in verdict.recommendation
    assert "shorter materialization interval" in verdict.recommendation


def test_draw_pilot_uses_roles_not_hardcoded_ig() -> None:
    report = run_pilot()
    row = next(
        effect for effect in report.effects.allocator_effects if effect.operand_key == "def:0"
    )
    assert row.role_correspondence.left.attributes["ig_id"] != row.role_correspondence.right.attributes["ig_id"]
    assert all("mnDiagram_DrawFighterHeaders" not in rule.rule_id for rule in report.applied_rules)
    assert all("fighter_id" not in rule.rule_id for rule in report.applied_rules)


def test_in_memory_and_persistent_store_reports_are_byte_identical() -> None:
    memory = run_pilot(store_factory=InMemoryEvidenceStore)
    persistent = run_pilot(store_factory=RecordingPersistentStore)
    assert render_json(memory) == render_json(persistent)
    assert render_text(memory) == render_text(persistent)
```

`run_pilot` is a test helper that materializes the fixture manifests and forwards its `store_factory` argument to `run_causal_diff`. `RecordingPersistentStore` implements `EvidenceStore` by wrapping `InMemoryEvidenceStore` while recording canonical batches, demonstrating that orchestration depends only on the storage-neutral protocol and leaves room for a later persistent provenance database.

- [ ] **Step 3: Run the pilot and diagnose only through generic layers**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_draw_fighter_headers.py -q
```

Expected before calibration: a failing assertion naming the exact missing or heuristic join. Improve the semantic adapter or generic join signature responsible for that evidence. Do not add function-name branches, fixed IG mappings, fixed offsets, or fixture-specific rule IDs. Repeat until the verdict is `causes` through proof-capable evidence.

- [ ] **Step 4: Run all causal-diff tests and commit the pilot**

```bash
cd tools/melee-agent
python -m pytest tests/test_causal_diff_store.py tests/test_causal_diff_bundles.py tests/test_causal_diff_inspect.py tests/test_causal_diff_backend_adapters.py tests/test_causal_diff_ownership.py tests/test_causal_diff_alignment.py tests/test_causal_diff_inference.py tests/test_causal_diff_cli.py tests/test_causal_diff_draw_fighter_headers.py -q
cd ../..
git add tools/melee-agent/tests/fixtures/causal_diff/draw_fighter_headers tools/melee-agent/tests/test_causal_diff_draw_fighter_headers.py tools/melee-agent/src/mwcc_debug/causal_diff
git commit -m "test: prove DrawFighterHeaders causal diff"
```

Expected: the complete causal-diff suite passes and the fixture contains no full unrelated translation-unit/compiler output.

---

### Task 10: Documentation and Full Verification

**Files:**
- Modify: `docs/CAPABILITIES.md`
- Modify: `.claude/skills/mwcc-debug/SKILL.md`
- Modify: `tools/melee-agent/tests/test_capabilities.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_docs_cli_reorg.py`

**Interfaces:**
- Consumes: shipped CLI behavior.
- Produces: discoverable documentation and final verification evidence.

- [ ] **Step 1: Add failing documentation/discoverability assertions**

```python
def test_capability_index_lists_causal_diff() -> None:
    names = {cap.name for cap in command_capabilities(app)}
    assert "debug inspect causal-diff" in names


def test_mwcc_debug_skill_documents_causal_diff() -> None:
    text = SKILL_PATH.read_text()
    assert "melee-agent debug inspect causal-diff" in text
    assert "read-only" in text
    assert "two artifact bundles" in text
```

- [ ] **Step 2: Update capability and skill documentation**

Document the exact command, bundle requirement, offset anchor, strict verdict meanings, exit codes, and the fact that it never generates artifacts or edits source. Add it after `lifetime-pressure` as the next read-only tool for cross-layer allocator/frame ownership tradeoffs. Regenerate `docs/CAPABILITIES.md` through the existing capabilities generator, not by hand.

- [ ] **Step 3: Run focused documentation and CLI surface tests**

```bash
cd tools/melee-agent
python -m pytest tests/test_capabilities.py tests/test_mwcc_debug_docs_cli_reorg.py tests/test_debug_cli_help_golden.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run the full melee-agent test suite**

```bash
cd tools/melee-agent
python -m pytest -q
```

Expected: full suite passes. If unrelated live/slow tests require unavailable external services, rerun the deterministic suite excluding only the repository's documented external-service markers and record the exact skipped tests.

- [ ] **Step 5: Run repository verification**

```bash
cd /Users/mike/.codex/worktrees/b8fa/melee
python configure.py
ninja
git diff --check
git status --short
```

Expected: configure and ninja succeed, `git diff --check` emits nothing, and status contains only the intended causal-diff implementation/documentation changes plus the pre-existing untracked `.superpowers/` visual-companion directory.

- [ ] **Step 6: Commit final documentation**

```bash
git add docs/CAPABILITIES.md .claude/skills/mwcc-debug/SKILL.md tools/melee-agent/tests/test_capabilities.py tools/melee-agent/tests/test_mwcc_debug_docs_cli_reorg.py
git commit -m "docs: document causal diff workflow"
```

- [ ] **Step 7: Perform final review**

Review the complete commit range for accidental source mutation, subprocess use in `causal_diff`, hardcoded pilot identifiers, unstable ordering, confidence upgrades, and unscoped cross-compile IDs. Run:

```bash
rg -n "subprocess|check_call|Popen|write_text|write_bytes|open\(.+,.*[wa]" tools/melee-agent/src/mwcc_debug/causal_diff
rg -n "mnDiagram_DrawFighterHeaders|fighter_id|0x234|\b66\b|\b58\b|0x44|0x48" tools/melee-agent/src/mwcc_debug/causal_diff
```

Expected: the first command reports only documentation/error text or no matches; the second command reports no production-code matches. Fixture and test matches are allowed outside `src/mwcc_debug/causal_diff`.
