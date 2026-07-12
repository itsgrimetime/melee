# Two-Frontier Delta Minimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable `melee-agent debug search delta-minimize` command that exhaustively recombines two retained source frontiers and returns the exact, bidirectionally minimized Pareto frontier for opcode graph, color graph, ObjObject order, and stack homes.

**Architecture:** A new `src.search.delta_minimize` package owns source-delta extraction, objective manifests, candidate evaluation, resumable storage, Pareto reduction, and rendering. Small reusable `mwcc_debug` modules expose each compiler-evidence profile. The CLI remains thin and injects existing score-source, checkdiff, pcdump, role-reanchor, and remote-inspector workflows.

**Tech Stack:** Python 3, Typer, tree-sitter-c, existing `mwcc_debug` parsers and score-source pipeline, pytest, JSON artifacts, remote `mwcc-inspect` shell workflow.

## Global Constraints

- Search only left/right source deltas; generate no novel bridge mutations.
- Enumerate every legal mask exactly once; default `--max-candidates` is 64.
- Reject more than 20 coupled atoms before mask enumeration.
- The all-zero and all-one masks must be legal and reproduce their input files byte-for-byte.
- Binary atoms cannot be incompatible; merge overlaps or fail extraction.
- Every successfully compiled viable mask must have every requested metric before publishing a completed frontier.
- Inspect every successfully compiled viable candidate unless `--no-objobjects` explicitly requests a provisional three-axis run.
- `matched` requires the repository exact-object/checkdiff gate; objective-zero alone is `joint-zero`.
- Do not patch repository source outside existing locked score-source/checkdiff staging.
- Add no third-party dependency.

---

## File map

- `tools/melee-agent/src/search/delta_minimize/contracts.py`: immutable JSON-friendly contracts and errors.
- `tools/melee-agent/src/search/delta_minimize/pareto.py`: dominance, grouping, directional minimization, status precedence.
- `tools/melee-agent/src/search/delta_minimize/delta.py`: primitive AST-anchored patches, endpoint reproduction, mask enumeration/materialization.
- `tools/melee-agent/src/search/delta_minimize/bindings.py`: supported direct-binding index, semantic coupling, fail-closed unsupported-shape detection.
- `tools/melee-agent/src/search/delta_minimize/objectives.py`: target schema, automatic target/donor inference, objective provenance.
- `tools/melee-agent/src/search/delta_minimize/store.py`: atomic phase ledger and content-addressed evidence cache.
- `tools/melee-agent/src/search/delta_minimize/evaluator.py`: score-source/checkdiff/pcdump/inspector adapters and profile completeness.
- `tools/melee-agent/src/search/delta_minimize/run.py`: resumable phase orchestration.
- `tools/melee-agent/src/search/delta_minimize/render.py`: text and JSON result rendering.
- `tools/melee-agent/src/mwcc_debug/opcode_graph.py`: normalized assembly CFG profile and distance.
- `tools/melee-agent/src/mwcc_debug/colorgraph_profile.py`: role-anchored allocator profile and distance.
- `tools/melee-agent/src/mwcc_debug/objobject_profile.py`: structured inspector ObjObject identities and order distance.
- `tools/melee-agent/src/mwcc_debug/stack_home_profile.py`: frame/stack-home profile adapter and distance.
- `tools/melee-agent/src/cli/debug/target.py`: expose full checkdiff evidence from score-source.
- `tools/melee-agent/src/search/cli/__init__.py`: register the command and parse donor overrides.
- `tools/melee-agent/tests/search/delta_minimize/`: unit and orchestration tests.
- `tools/melee-agent/tests/fixtures/delta_minimize/`: compact sources and compiler-evidence fixtures.
- `tools/melee-agent/tests/golden/debug_cli_help/debug__search__delta-minimize.txt`: CLI help golden.

### Task 1: Contracts and exact Pareto reduction

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/__init__.py`
- Create: `tools/melee-agent/src/search/delta_minimize/contracts.py`
- Create: `tools/melee-agent/src/search/delta_minimize/pareto.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/__init__.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_pareto.py`

**Interfaces:**
- Produces: `DeltaMinimizeError`, `AxisDistances`, `CandidateProfile`, `ParetoGroup`, `ParetoSummary`, `reduce_pareto(profiles)`.
- `CandidateProfile.viable` means compilation succeeded and the requested function exists in its pcdump.

- [ ] **Step 1: Write failing Pareto and completeness tests**

```python
from src.search.delta_minimize.contracts import AxisDistances, CandidateProfile
from src.search.delta_minimize.pareto import reduce_pareto


def profile(cid, mask, axes, *, exact=False, complete=True):
    return CandidateProfile(
        candidate_id=cid,
        mask=mask,
        source_hash=cid,
        source_path=f"/{cid}.c",
        viable=True,
        compile_status="ok",
        axes=axes,
        complete=complete,
        exact_object_match=exact,
    )


def test_raw_frontier_keeps_all_masks_and_minimizes_both_directions():
    v = AxisDistances((0, 0), (1, 0, 0, 0, 0, 0), (0, 0), (0, 0, 0, 0))
    result = reduce_pareto([profile("left-near", 0b001, v), profile("right-near", 0b110, v)], atom_count=3)
    assert result.candidate_ids == ("left-near", "right-near")
    assert result.groups[0].minimal_from_left == ("left-near",)
    assert result.groups[0].minimal_from_right == ("right-near",)


def test_viable_incomplete_profile_blocks_exact_reduction():
    complete = profile("complete", 0, AxisDistances.zero())
    incomplete = profile("incomplete", 1, None, complete=False)
    with pytest.raises(DeltaMinimizeError, match="incomplete-candidate-evidence"):
        reduce_pareto([complete, incomplete], atom_count=1)


def test_exact_match_status_precedes_proxy_joint_zero():
    nonzero = AxisDistances((0, 0), (0, 0, 0, 0, 0, 0), (1, 0), (0, 0, 0, 0))
    result = reduce_pareto([profile("winner", 0, nonzero, exact=True)], atom_count=0)
    assert result.status == "matched"
    assert result.exact_match_candidate_ids == ("winner",)
```

- [ ] **Step 2: Run the tests and confirm import failures**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_pareto.py -q`

Expected: FAIL with `ModuleNotFoundError: src.search.delta_minimize`.

- [ ] **Step 3: Add the contracts**

```python
@dataclass(frozen=True, order=True)
class AxisDistances:
    opcode: tuple[int, int]
    color: tuple[int, int, int, int, int, int]
    objobjects: tuple[int, int]
    stack_homes: tuple[int, int, int, int]

    @classmethod
    def zero(cls) -> "AxisDistances":
        return cls((0, 0), (0, 0, 0, 0, 0, 0), (0, 0), (0, 0, 0, 0))


@dataclass(frozen=True)
class CandidateProfile:
    candidate_id: str
    mask: int
    source_hash: str
    source_path: str
    viable: bool
    compile_status: str
    axes: AxisDistances | None
    complete: bool
    exact_object_match: bool = False
    blockers: tuple[str, ...] = ()


class DeltaMinimizeError(RuntimeError):
    def __init__(self, reason: str, details: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})


@dataclass(frozen=True)
class ParetoGroup:
    objective_vector: AxisDistances
    candidate_ids: tuple[str, ...]
    minimal_from_left: tuple[str, ...]
    minimal_from_right: tuple[str, ...]
    representative: str


@dataclass(frozen=True)
class ParetoSummary:
    status: str
    candidate_ids: tuple[str, ...]
    groups: tuple[ParetoGroup, ...]
    best_next: str | None
    exact_match_candidate_ids: tuple[str, ...]
    joint_solutions: tuple[str, ...]
    joint_zero_all_candidate_ids: tuple[str, ...]
```

Add JSON-friendly `to_dict()` methods that preserve these exact field names.

- [ ] **Step 4: Implement componentwise dominance and directional minimization**

```python
def dominates(a: AxisDistances, b: AxisDistances) -> bool:
    pairs = ((a.opcode, b.opcode), (a.color, b.color),
             (a.objobjects, b.objobjects), (a.stack_homes, b.stack_homes))
    return all(x <= y for x, y in pairs) and any(x < y for x, y in pairs)


def reduce_pareto(profiles: Sequence[CandidateProfile], *, atom_count: int) -> ParetoSummary:
    incomplete = [p.candidate_id for p in profiles if p.viable and not p.complete]
    if incomplete:
        raise DeltaMinimizeError("incomplete-candidate-evidence", {"candidate_ids": incomplete})
    viable = [p for p in profiles if p.viable and p.axes is not None]
    frontier = [p for p in viable if not any(
        q.candidate_id != p.candidate_id and dominates(q.axes, p.axes)
        for q in viable
    )]
    # Group by AxisDistances, retain every raw ID, and choose subset-minimal
    # masks from zero and complement-minimal masks from all-one.
    return _build_summary(frontier, profiles, atom_count=atom_count)
```

Implement status precedence `matched > joint-zero > frontier`, raw membership, vector groups, exact-match retention, and deterministic `best_next` exactly as the spec defines.

- [ ] **Step 5: Run focused tests**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_pareto.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/search/delta_minimize tools/melee-agent/tests/search/delta_minimize
git commit -m "feat: add delta frontier contracts"
```

### Task 2: AST-anchored binary delta lattice

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/delta.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_delta.py`

**Interfaces:**
- Produces: `DeltaPatch`, `DeltaAtom`, `DeltaManifest`, `MaterializedCandidate`, `extract_primitive_manifest()`, `enumerate_legal_masks()`, `materialize_mask()`.
- Consumes: `DeltaMinimizeError` from Task 1 and `src.common.tree_sitter_c.get_parser`.

- [ ] **Step 1: Write failing endpoint, presentation, budget, and overlap tests**

```python
def manifest_with_independent_atoms(count):
    atoms = tuple(DeltaAtom(
        atom_id=f"a{i}", kind="expression", patches=(), summary=f"atom {i}"
    ) for i in range(count))
    return DeltaManifest(
        schema_version="delta-manifest.v1", function="f",
        left_hash="left", right_hash="right", atoms=atoms,
    )


def test_endpoints_are_byte_exact_and_formatting_is_one_atom():
    left = "int f(int x) {\n    return x + 1;\n}\n"
    right = "int f(int x){\n  return x + 2;\n}\n"
    manifest = extract_primitive_manifest(left, right, function="f")
    masks = enumerate_legal_masks(manifest, max_candidates=64)
    assert materialize_mask(left, manifest, 0) == left
    assert materialize_mask(left, manifest, (1 << len(manifest.atoms)) - 1) == right
    assert sum(a.kind == "presentation-only" for a in manifest.atoms) <= 1
    assert 0 in masks and (1 << len(manifest.atoms)) - 1 in masks


def test_budget_fails_before_returning_partial_masks():
    manifest = manifest_with_independent_atoms(7)
    with pytest.raises(DeltaMinimizeError, match="candidate-budget-exceeded") as exc:
        enumerate_legal_masks(manifest, max_candidates=64)
    assert exc.value.details["required"] == 128


def test_unmergeable_overlap_fails_extraction():
    with pytest.raises(DeltaMinimizeError, match="unmergeable-overlapping-delta"):
        extract_primitive_manifest(OVERLAPPING_LEFT, OVERLAPPING_RIGHT, function="f")
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_delta.py -q`

Expected: FAIL because `delta.py` does not exist.

- [ ] **Step 3: Implement patch and manifest contracts**

```python
@dataclass(frozen=True)
class DeltaPatch:
    left_start: int
    left_end: int
    left_text: str
    right_start: int
    right_end: int
    right_text: str
    anchor_kind: str
    anchor_symbol: str


@dataclass(frozen=True)
class DeltaAtom:
    atom_id: str
    kind: str
    patches: tuple[DeltaPatch, ...]
    requires: tuple[str, ...] = ()
    affected_functions: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class DeltaManifest:
    schema_version: str
    function: str
    left_hash: str
    right_hash: str
    atoms: tuple[DeltaAtom, ...]


@dataclass(frozen=True)
class MaterializedCandidate:
    candidate_id: str
    mask: int
    source_hash: str
    source_path: Path
    applied_atom_ids: tuple[str, ...]
```

Use `difflib.SequenceMatcher` to find exact textual replacements, tree-sitter to attach each replacement to the smallest supported node, and one aggregate presentation atom for remaining whitespace-only opcodes.

- [ ] **Step 4: Implement exact materialization and legal-mask counting**

```python
def materialize_mask(left: str, manifest: DeltaManifest, mask: int) -> str:
    selected = [patch for i, atom in enumerate(manifest.atoms)
                if mask & (1 << i) for patch in atom.patches]
    out = left
    for patch in sorted(selected, key=lambda p: p.left_start, reverse=True):
        if out[patch.left_start:patch.left_end] != patch.left_text:
            raise DeltaMinimizeError("invalid-materialized-anchor", {"atom": patch.anchor_symbol})
        out = out[:patch.left_start] + patch.right_text + out[patch.left_end:]
    return out


def enumerate_legal_masks(manifest: DeltaManifest, *, max_candidates: int) -> tuple[int, ...]:
    if len(manifest.atoms) > 20:
        raise DeltaMinimizeError("atom-space-too-large", {"atom_count": len(manifest.atoms)})
    ids = {a.atom_id: i for i, a in enumerate(manifest.atoms)}
    legal = tuple(mask for mask in range(1 << len(manifest.atoms))
                  if all(not (mask & (1 << i)) or all(mask & (1 << ids[r]) for r in a.requires)
                         for i, a in enumerate(manifest.atoms)))
    if len(legal) > max_candidates:
        raise DeltaMinimizeError("candidate-budget-exceeded", {"required": len(legal), "limit": max_candidates})
    return legal
```

Validate zero/all-one legality and byte-exact endpoint reproduction before returning the manifest.

- [ ] **Step 5: Run tests**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_delta.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/search/delta_minimize/delta.py tools/melee-agent/tests/search/delta_minimize/test_delta.py
git commit -m "feat: add binary source delta lattice"
```

### Task 3: Semantic coupling and supported-binding gate

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/bindings.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/delta.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_bindings.py`

**Interfaces:**
- Produces: `build_binding_index(source)`, `couple_semantic_atoms(left, right, atoms)`, `validate_supported_bindings()`.
- `extract_delta_manifest()` becomes the public composition of primitive extraction plus coupling.

- [ ] **Step 1: Write failing direct-call coupling and fail-closed tests**

```python
def test_parameter_and_call_reorder_become_one_atom():
    manifest = extract_delta_manifest(PARAM_LEFT, PARAM_RIGHT, function="draw")
    atom = next(a for a in manifest.atoms if "helper parameter reorder" in a.summary)
    assert {p.anchor_kind for p in atom.patches} == {"parameter_list", "argument_list"}


@pytest.mark.parametrize("left,right", [
    (MACRO_CALL_LEFT, MACRO_CALL_RIGHT),
    (INDIRECT_CALL_LEFT, INDIRECT_CALL_RIGHT),
    (SHADOWED_CALL_LEFT, SHADOWED_CALL_RIGHT),
    (CONDITIONAL_LEFT, CONDITIONAL_RIGHT),
])
def test_unsupported_changed_binding_fails_closed(left, right):
    with pytest.raises(DeltaMinimizeError, match="unsupported-semantic-binding"):
        extract_delta_manifest(left, right, function="draw")
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_bindings.py -q`

Expected: FAIL because semantic coupling is absent.

- [ ] **Step 3: Build a conservative TU-local binding index**

```python
@dataclass(frozen=True)
class CallBinding:
    callee: str
    call_span: tuple[int, int]
    argument_span: tuple[int, int]
    argument_texts: tuple[str, ...]


@dataclass(frozen=True)
class FunctionBinding:
    name: str
    definition_span: tuple[int, int]
    parameter_names: tuple[str, ...]
    parameter_span: tuple[int, int]
    direct_calls: tuple[CallBinding, ...]


@dataclass(frozen=True)
class BindingBlocker:
    symbol: str
    reason: str
    span: tuple[int, int]


@dataclass(frozen=True)
class BindingIndex:
    functions: Mapping[str, FunctionBinding]
    blockers: tuple[BindingBlocker, ...]


def validate_supported_bindings(index: BindingIndex, changed_names: set[str]) -> None:
    blockers = [b for b in index.blockers if b.symbol in changed_names]
    if blockers:
        raise DeltaMinimizeError("unsupported-semantic-binding", {
            "blockers": [asdict(b) for b in blockers]
        })
```

The tree walk must record direct identifier calls, preprocessor ancestors, local declarations shadowing function names, indirect call expressions, and macro-like call sites. Reject changed affected bindings with any blocker.

- [ ] **Step 4: Couple permutation/rename patches and collapse dependency cycles**

```python
def _parameter_permutation(left: FunctionBinding, right: FunctionBinding) -> tuple[int, ...] | None:
    if sorted(left.parameter_names) != sorted(right.parameter_names):
        return None
    order = tuple(left.parameter_names.index(name) for name in right.parameter_names)
    return order if order != tuple(range(len(order))) else None


class UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left, right):
        self.parent[self.find(right)] = self.find(left)


def _stable_composite_id(group):
    raw = "\0".join(sorted(atom.atom_id for atom in group)).encode()
    return "delta-" + hashlib.sha256(raw).hexdigest()[:16]


def _materialize_composite_atoms(groups, atoms):
    by_root = defaultdict(list)
    for atom in atoms:
        by_root[groups.find(atom.atom_id)].append(atom)
    return tuple(DeltaAtom(
        atom_id=_stable_composite_id(group),
        kind="semantic-composite" if len(group) > 1 else group[0].kind,
        patches=tuple(sorted((p for atom in group for p in atom.patches), key=lambda p: p.left_start)),
        requires=tuple(sorted(set(r for atom in group for r in atom.requires)
                              - {a.atom_id for a in group})),
        affected_functions=tuple(sorted(set(f for atom in group for f in atom.affected_functions))),
        summary="; ".join(atom.summary for atom in group if atom.summary),
    ) for group in by_root.values())


def couple_semantic_atoms(left_index, right_index, atoms):
    groups = UnionFind(a.atom_id for a in atoms)
    # Union a changed function parameter patch with every changed direct-call
    # argument patch for the same symbol; union definition/call patches for a
    # uniquely paired rename; union overlapping patches. Fail if pairing is not unique.
    return _materialize_composite_atoms(groups, atoms)
```

Require every direct call to preserve the parent binding under each legal mask. Merge overlapping replacements and dependency SCCs; never emit incompatibilities.

- [ ] **Step 5: Run extractor tests**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_delta.py tests/search/delta_minimize/test_bindings.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/search/delta_minimize tools/melee-agent/tests/search/delta_minimize
git commit -m "feat: couple semantic source deltas"
```

### Task 4: Opcode graph metric

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/opcode_graph.py`
- Create: `tools/melee-agent/tests/test_opcode_graph.py`

**Interfaces:**
- Produces: `OpcodeGraph`, `parse_opcode_graph(lines)`, `opcode_graph_distance(expected, current, structural_status)`.

- [ ] **Step 1: Write failing normalization and contradiction tests**

```python
def test_register_only_diff_has_zero_opcode_graph_distance():
    expected = parse_opcode_graph(EXPECTED_REGISTER_SWAP)
    current = parse_opcode_graph(CURRENT_REGISTER_SWAP)
    assert opcode_graph_distance(expected, current, structural_status="structural-match") == (0, 0)


def test_branch_edge_change_is_not_zero():
    assert opcode_graph_distance(parse_opcode_graph(CFG_A), parse_opcode_graph(CFG_B),
                                 structural_status="opcode-mismatch") == (0, 1)


def test_zero_graph_with_rejected_structural_gate_is_incomplete_evidence():
    with pytest.raises(ValueError, match="opcode-structural-contradiction"):
        opcode_graph_distance(parse_opcode_graph(CFG_A), parse_opcode_graph(CFG_A),
                              structural_status="structural-mismatch")
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/test_opcode_graph.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement CFG parsing and distance**

```python
@dataclass(frozen=True)
class OpcodeGraph:
    nodes: tuple[tuple[str, ...], ...]
    edges: frozenset[tuple[int, int]]


def opcode_graph_distance(expected: OpcodeGraph, current: OpcodeGraph, *, structural_status: str) -> tuple[int, int]:
    changed_nodes = sum(a != b for a, b in zip_longest(expected.nodes, current.nodes, fillvalue=()))
    changed_edges = len(expected.edges.symmetric_difference(current.edges))
    if changed_nodes == changed_edges == 0 and structural_status != "structural-match":
        raise ValueError("opcode-structural-contradiction")
    return changed_nodes, changed_edges
```

Parse `+OFFSET: BYTES opcode operands`, ignore relocation-only lines, split blocks at branch targets/fallthroughs, preserve opcode, and discard registers/immediates/labels only from operands.

- [ ] **Step 4: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/test_opcode_graph.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/mwcc_debug/opcode_graph.py tools/melee-agent/tests/test_opcode_graph.py
git commit -m "feat: score normalized opcode graphs"
```

### Task 5: Role-anchored color graph metric

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/colorgraph_profile.py`
- Create: `tools/melee-agent/tests/test_colorgraph_profile.py`

**Interfaces:**
- Produces: `ColorGraphProfile`, `build_colorgraph_profile(pcdump, function, class_id, role_map)`, `colorgraph_distance(candidate, donor, desired_phys)`.
- Consumes: `parse_hook_events()` and role maps of `candidate_ig -> stable_original_ig` from `role_reanchor.ReanchorResult.matched`.

- [ ] **Step 1: Write failing role-renumber and donor-distance tests**

```python
def test_renumbered_igs_compare_by_stable_roles():
    donor = build_colorgraph_profile(DONOR_PCDUMP, "f", 0, {66: 1, 70: 2})
    candidate = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1, 75: 2})
    distance = colorgraph_distance(candidate, donor, desired_phys={1: 22, 2: 30})
    assert distance.assignment_misses == 0
    assert distance.interference_edge_delta == 0


def test_unstable_target_role_marks_profile_incomplete():
    profile = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {75: 2}, required_roles={1, 2})
    assert profile.complete is False
    assert profile.missing_roles == (1,)
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/test_colorgraph_profile.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement stable-role profiles**

```python
@dataclass(frozen=True)
class ColorGraphProfile:
    assignments: tuple[tuple[int, int], ...]
    simplify_order: tuple[int, ...]
    select_order: tuple[int, ...]
    interference_edges: frozenset[tuple[int, int]]
    coalesce_pairs: frozenset[tuple[int, int]]
    spills: frozenset[int]
    complete: bool
    missing_roles: tuple[int, ...] = ()


@dataclass(frozen=True)
class ColorDistance:
    assignment_misses: int
    simplify_order_inversions: int
    select_order_inversions: int
    interference_edge_delta: int
    coalesce_delta: int
    spill_delta: int

    def as_tuple(self):
        return astuple(self)
```

Map decisions, simplify entries, interferers, coalesce mappings, and spills through the stable role map. Count Kendall inversions over the shared complete role set and symmetric differences for sets.

- [ ] **Step 4: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/test_colorgraph_profile.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/mwcc_debug/colorgraph_profile.py tools/melee-agent/tests/test_colorgraph_profile.py
git commit -m "feat: score role-anchored color graphs"
```

### Task 6: ObjObject identities and order metric

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/objobject_profile.py`
- Modify: `tools/melee-agent/src/mwcc_debug/inspect_parser.py`
- Create: `tools/melee-agent/tests/test_objobject_profile.py`

**Interfaces:**
- Produces: `parse_objobject_profile(inspect_text, function)`, `objobject_order_distance(candidate, donor)`.
- Consumes: `parse_inspect_snapshots()`.

- [ ] **Step 1: Write failing address-normalization and ambiguity tests**

```python
def test_addresses_do_not_change_identity_or_order():
    a = parse_objobject_profile(INSPECT_A, "f")
    b = parse_objobject_profile(INSPECT_SAME_OBJECTS_NEW_ADDRESSES, "f")
    assert objobject_order_distance(a, b) == (0, 0)


def test_reordered_unique_objects_count_inversions():
    assert objobject_order_distance(
        parse_objobject_profile(INSPECT_A, "f"),
        parse_objobject_profile(INSPECT_REORDERED, "f"),
    ) == (0, 1)


def test_indistinguishable_repeated_objects_are_incomplete():
    profile = parse_objobject_profile(INSPECT_AMBIGUOUS_DUPLICATES, "f")
    assert profile.complete is False
    assert profile.blocker == "ambiguous-objobject-identity"
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/test_objobject_profile.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Add structured ObjObject parsing**

```python
@dataclass(frozen=True)
class ObjObjectIdentity:
    kind: str
    source_name: str
    type_name: str
    scope: str
    expression: str


@dataclass(frozen=True)
class ObjObjectProfile:
    identities: tuple[ObjObjectIdentity, ...]
    complete: bool
    blocker: str | None = None
```

Select the `Frontend: OBJOBJECTS` snapshot, strip hexadecimal/process addresses, normalize whitespace/register-like IDs, and form identities from labeled kind/name/type/scope/expression fields. If duplicate identities cannot be disambiguated by occurrence evidence, return incomplete.

- [ ] **Step 4: Implement LCS membership and Kendall order distance**

```python
def objobject_order_distance(candidate, donor):
    if not candidate.complete or not donor.complete:
        raise ValueError("incomplete-objobject-evidence")
    missing_extra = multiset_delta(candidate.identities, donor.identities)
    common = stable_common_identity_order(candidate.identities, donor.identities)
    return missing_extra, kendall_inversions(common.candidate, common.donor)
```

- [ ] **Step 5: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/test_objobject_profile.py tests/test_mwcc_debug_inspect_parser.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/mwcc_debug/objobject_profile.py tools/melee-agent/src/mwcc_debug/inspect_parser.py tools/melee-agent/tests/test_objobject_profile.py
git commit -m "feat: score inspector ObjObject order"
```

### Task 7: Generalized stack-home metric

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/stack_home_profile.py`
- Create: `tools/melee-agent/tests/test_stack_home_profile.py`

**Interfaces:**
- Produces: `build_stack_home_profile(frame_report, stack_slot_report)`, `stack_home_distance(candidate, reference)`.
- Consumes: `analyze_frame_reservations()` reports and `explain_stack_slot_localizer()` output.

- [ ] **Step 1: Write failing named, symbolic, compiler-temp, and ambiguity tests**

```python
def test_compiler_temp_offset_is_scored_with_stable_first_def_identity():
    expected = build_stack_home_profile(EXPECTED_FRAME_REPORT, EXPECTED_SLOT_BRIDGE)
    current = build_stack_home_profile(CURRENT_FRAME_REPORT, CURRENT_SLOT_BRIDGE)
    assert stack_home_distance(current, expected).as_tuple() == (1, 4, 0, 0)


def test_unresolved_compiler_temp_is_incomplete():
    profile = build_stack_home_profile(FRAME_REPORT, AMBIGUOUS_SLOT_BRIDGE)
    assert profile.complete is False
    assert profile.blockers == ("ambiguous-compiler-temp-home",)
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/test_stack_home_profile.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement normalized home identities and distance**

```python
@dataclass(frozen=True)
class StackHome:
    identity: str
    offset: int
    order: int
    reference_kind: str


@dataclass(frozen=True)
class StackHomeProfile:
    frame_size: int | None
    homes: tuple[StackHome, ...]
    complete: bool
    blockers: tuple[str, ...] = ()


def stack_home_distance(candidate, reference) -> StackHomeDistance:
    if not candidate.complete or not reference.complete:
        raise ValueError("incomplete-stack-home-evidence")
    # Join by identity, count missing/moved offsets, compare joined order,
    # and take the absolute frame-size delta.
    return _distance(join_homes(candidate.homes, reference.homes), candidate.frame_size, reference.frame_size)
```

Use named/symbolic assignment fields from `frame_report["current"]["stack_home_assignments"]`. For anonymous compiler homes, derive identity from opcode, normalized first-def signature, and unique source-owner evidence in the stack-slot bridge; ambiguous owners make the profile incomplete.

- [ ] **Step 4: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/test_stack_home_profile.py tests/test_frame_reservations.py tests/test_stack_slot_bridge.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/mwcc_debug/stack_home_profile.py tools/melee-agent/tests/test_stack_home_profile.py
git commit -m "feat: score generalized stack homes"
```

### Task 8: Versioned target and donor inference

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/objectives.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_objectives.py`

**Interfaces:**
- Produces: `load_color_target()`, `infer_objective_manifest()`, `ObjectiveManifest` serialization.
- Consumes: `role_descriptor.Compile`, `build_target_spec`, `role_reanchor.reanchor`, parent raw evidence, and an injected force-target derivation callable compatible with `_derive_force_phys_from_register_diff_lines`.

```python
@dataclass(frozen=True)
class LoadedColorTarget:
    function: str
    class_id: int
    baseline_dump: Path
    force_phys: Mapping[int, int]
    coalesce_preservation: bool


@dataclass(frozen=True)
class AxisReference:
    reference_kind: str
    reference_artifact: str
    donor: str | None
    inference_reason: str
    override: bool
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectiveManifest:
    schema_version: str
    function: str
    class_id: int
    target_spec: Mapping[str, Any]
    desired_phys: Mapping[int, int]
    color_donor: str | None
    objobject_donor: str
    stack_home_donor: str | None
    references: Mapping[str, AxisReference]
```

- [ ] **Step 1: Write failing schema, cross-parent, and donor-tie tests**

```python
def test_color_target_v1_validates_function_and_baseline(tmp_path):
    path = write_target(tmp_path, schema_version="delta-minimize-color-target.v1")
    target = load_color_target(path, function="draw")
    assert target.force_phys == {66: 22, 67: 21}


def test_conflicting_parent_role_targets_require_explicit_target():
    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-target"):
        infer_objective_manifest(LEFT_PARENT, RIGHT_PARENT_CONFLICT, target_path=None, donor_overrides={})


def test_equal_assignment_distance_with_different_graphs_requires_color_donor():
    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-donor"):
        infer_objective_manifest(TIED_LEFT, TIED_RIGHT, target_path=TARGET, donor_overrides={})
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_objectives.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement the target schema loader**

```python
def load_color_target(path: Path, *, function: str) -> LoadedColorTarget:
    data = yaml.safe_load(path.read_text())
    if data.get("schema_version") != "delta-minimize-color-target.v1":
        raise DeltaMinimizeError("unsupported-color-target-schema")
    if data.get("function") != function:
        raise DeltaMinimizeError("color-target-function-mismatch")
    baseline = (path.parent / data["baseline_dump"]).resolve() if not Path(data["baseline_dump"]).is_absolute() else Path(data["baseline_dump"])
    force_phys = {int(k): int(v) for k, v in data["force_phys"].items()}
    return _validate_loaded_target(data, baseline, force_phys)
```

Build a `role_descriptor.TargetSpec` from the baseline pcdump and source, then require round-trip role stability for every desired assignment.

- [ ] **Step 4: Implement automatic reference and donor inference**

```python
def infer_objective_manifest(left, right, *, target_path, donor_overrides, derive_force_target):
    target = load_color_target(target_path, function=left.function) if target_path else _derive_and_cross_check(left, right, derive_force_target)
    color_donor = _infer_color_donor(left, right, target, donor_overrides.get("color"))
    obj_donor = donor_overrides.get("objobjects") or color_donor
    stack_donor = _infer_stack_donor(left, right, donor_overrides.get("stack-homes"))
    return ObjectiveManifest.from_parents(target, left, right, color_donor, obj_donor, stack_donor)
```

Absolute opcode truth always comes from expected assembly. Secondary color components use the selected color donor. ObjObjects use the color donor unless overridden. Unresolved anonymous stack homes use the strictly better stack donor; tied unresolved homes fail closed.

- [ ] **Step 5: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_objectives.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/search/delta_minimize/objectives.py tools/melee-agent/tests/search/delta_minimize/test_objectives.py
git commit -m "feat: infer delta search objectives"
```

### Task 9: Atomic resumable run store

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/store.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_store.py`

**Interfaces:**
- Produces: `DeltaRunStore`, `EvidenceKey`, atomic `write_json()`, provenance-checked `load_evidence()`.
- Consumes: existing `src.search.store.ArtifactStore` for source blobs.

```python
@dataclass(frozen=True)
class EvidenceKey:
    source_hash: str
    function: str
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    objective_manifest_hash: str
    parser_schema_hash: str
    inspector_version: str

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ParentEvidenceKey:
    source_hash: str
    function: str
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    parser_schema_hash: str
    inspector_version: str


class DeltaRunStore:
    def __init__(self, root: Path, provenance: Mapping[str, str] | None = None):
        self.root = root
        self.provenance = dict(provenance or {})
        self.sources = ArtifactStore(root / "artifacts")

    def inspect_output_path(self, candidate_id: str) -> Path:
        return self.root / "evidence" / candidate_id / "inspect.txt"

    def bind_provenance(self, provenance: Mapping[str, str]) -> None:
        self.provenance = dict(provenance)

    def evidence_key(self, candidate, config) -> EvidenceKey:
        return EvidenceKey(
            source_hash=candidate.source_hash,
            function=config.function,
            cflags_hash=self.provenance["cflags_hash"],
            compiler_fingerprint=self.provenance["compiler_fingerprint"],
            expected_object_hash=self.provenance["expected_object_hash"],
            objective_manifest_hash=self.provenance["objective_manifest_hash"],
            parser_schema_hash=self.provenance["parser_schema_hash"],
            inspector_version=self.provenance["inspector_version"],
        )
```

- [ ] **Step 1: Write failing resume, stale-provenance, and interrupted-write tests**

```python
def test_complete_evidence_resumes_without_runner(tmp_path):
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete", "value": 7})
    assert store.load_evidence(KEY)["value"] == 7


def test_changed_compiler_fingerprint_invalidates_cache(tmp_path):
    store = DeltaRunStore(tmp_path)
    store.write_evidence(KEY, {"status": "complete"})
    assert store.load_evidence(replace(KEY, compiler_fingerprint="new")) is None


def test_atomic_write_never_replaces_previous_json_on_failure(tmp_path, monkeypatch):
    store = DeltaRunStore(tmp_path)
    store.write_result({"status": "frontier"})
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        store.write_result({"status": "matched"})
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "frontier"
```

- [ ] **Step 2: Verify failure**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_store.py -q`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement content keys and atomic JSON**

```python
def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
```

`EvidenceKey.digest()` must hash source, function, cflags, compiler, expected object, objective manifest, parser schemas, and inspector version. Cache payloads include the unhashed provenance and are rejected on any mismatch.
Parent capture uses `ParentEvidenceKey`, which intentionally omits the not-yet-
derived objective hash. Candidate capture begins only after
`bind_provenance()` and uses the full `EvidenceKey`.
`DeltaRunStore.write_color_target(target_spec)` writes the versioned target to
`objective/color-target.json` with `write_json_atomic()` and returns that path;
the evaluator passes the same immutable file to every score-source call.

- [ ] **Step 4: Run tests and commit**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_store.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/search/delta_minimize/store.py tools/melee-agent/tests/search/delta_minimize/test_store.py
git commit -m "feat: cache delta search evidence"
```

### Task 10: Candidate capture and four-axis evaluation

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/target.py:2180-2225`
- Modify: `tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py`
- Create: `tools/melee-agent/src/search/delta_minimize/evaluator.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_evaluator.py`
- Create: `tools/melee-agent/tests/test_delta_score_source_evidence.py`

**Interfaces:**
- Produces: `RawCandidateEvidence`, `EvaluationBackends`, `capture_candidate()`, `profile_candidate()`.
- Consumes: `score_retained_source_rows`, strict inspector runner, four metric modules, `ObjectiveManifest`, and `DeltaRunStore`.

```python
@dataclass(frozen=True)
class RawCandidateEvidence:
    candidate_id: str
    mask: int
    source_path: str
    source_hash: str
    compile_status: str
    viable: bool
    pcdump_path: str | None
    checkdiff_evidence: Mapping[str, Any] | None
    inspect_text: str | None
    compiler_stderr: str
    blockers: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawCandidateEvidence":
        return cls(**{**data, "blockers": tuple(data.get("blockers", ()))})


@dataclass(frozen=True)
class ParentEvidenceBundle:
    left: RawCandidateEvidence
    right: RawCandidateEvidence
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    inspector_version: str


@dataclass(frozen=True)
class CandidateEvaluationConfig:
    melee_root: Path
    function: str
    cflags_from: Path
    target_path: Path
    output_dir: Path
    include_objobjects: bool
    score_timeout: float = 120.0
    inspect_timeout: int = 180


def _score_source_config(config: CandidateEvaluationConfig) -> ScoreSourceConfig:
    return ScoreSourceConfig(
        repo_root=config.melee_root,
        function=config.function,
        target=config.target_path,
        cflags_from=config.cflags_from,
        expression_source=config.cflags_from,
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=config.output_dir,
        timeout=config.score_timeout,
        checkdiff_guard=True,
        full_unit_source=True,
    )
```

- [ ] **Step 1: Expose full checkdiff evidence from score-source with a failing regression test**

```python
def test_score_source_json_includes_checkdiff_evidence(monkeypatch, tmp_path):
    result = invoke_score_source_with_real_score(
        monkeypatch, tmp_path,
        checkdiff_payload={"function": "f", "match": False,
                           "target_asm": ["+000: 38 60 00 00 li r3,0"],
                           "current_asm": ["+000: 38 80 00 00 li r4,0"]},
    )
    assert result["checkdiff_evidence"]["target_asm"][0].endswith("li r3,0")
```

Run: `cd tools/melee-agent && pytest tests/test_delta_score_source_evidence.py -q`

Expected: FAIL because the field is absent.

- [ ] **Step 2: Preserve the checkdiff payload in score-source JSON**

```python
checkdiff_payload = getattr(real_score, "checkdiff_payload", None)
if isinstance(checkdiff_payload, dict):
    payload["checkdiff_evidence"] = checkdiff_payload
```

Add `checkdiff_evidence` to `CandidateScore` and `source_row_to_candidate_score()` without changing existing guard fields.

- [ ] **Step 3: Write evaluator completeness tests**

```python
def test_compile_rejection_is_nonviable_not_run_incomplete():
    evidence = capture_candidate(CANDIDATE, CONFIG, backends=rejecting_backends())
    assert evidence.compile_status == "rejected"
    assert evidence.viable is False


@pytest.mark.parametrize("missing", ["pcdump_path", "checkdiff_evidence", "inspect_text"])
def test_viable_missing_evidence_is_incomplete(missing):
    profile = profile_candidate(raw_evidence_without(missing), OBJECTIVE)
    assert profile.viable is True
    assert profile.complete is False
    assert f"missing-{missing.replace('_', '-')}" in profile.blockers
```

- [ ] **Step 4: Implement strict capture and profiling**

```python
@dataclass(frozen=True)
class EvaluationBackends:
    score_rows: Callable[..., list[dict[str, Any]]]
    inspect_source: Callable[[Path, str, Path], str]


def capture_candidate(candidate, config, *, backends, store):
    key = store.evidence_key(candidate, config)
    cached = store.load_evidence(key)
    if cached is not None:
        return RawCandidateEvidence.from_dict(cached)
    row = backends.score_rows([{
        "candidate_id": candidate.candidate_id,
        "source_file": str(candidate.source_path),
        "source_retained": str(candidate.source_path),
        "full_unit_source": True,
    }], _score_source_config(config))[0]
    evidence = _classify_score_row(row)
    if evidence.viable and config.include_objobjects:
        evidence = replace(evidence, inspect_text=backends.inspect_source(
            Path(evidence.source_path), config.function,
            store.inspect_output_path(candidate.candidate_id)))
    store.write_evidence(key, evidence.to_dict())
    return evidence
```

`profile_candidate()` must build role reanchors, opcode/color/ObjObject/stack profiles, set `complete=False` for any missing or ambiguous required evidence, and set `exact_object_match` only from checkdiff `match is True`.

- [ ] **Step 5: Run focused tests and commit**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_evaluator.py tests/test_delta_score_source_evidence.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/cli/debug/target.py tools/melee-agent/src/mwcc_debug/source_candidate_scoring.py tools/melee-agent/src/search/delta_minimize/evaluator.py tools/melee-agent/tests
git commit -m "feat: evaluate delta candidates on four axes"
```

### Task 11: Resumable orchestration

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/run.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/__init__.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_run.py`

**Interfaces:**
- Produces: `DeltaMinimizeConfig`, `DeltaMinimizeResult`, `run_delta_minimize(config, backends)`.
- Consumes all prior task interfaces.

```python
@dataclass(frozen=True)
class DeltaMinimizeConfig:
    function: str
    left: Path
    right: Path
    out_dir: Path
    max_candidates: int
    target_path: Path | None
    donor_overrides: Mapping[str, str]
    include_objobjects: bool
    melee_root: Path
    cflags_from: Path


@dataclass(frozen=True)
class DeltaMinimizeResult:
    schema_version: str
    status: str
    exact_four_axis: bool
    function: str
    objective_manifest: Mapping[str, Any]
    delta_manifest: Mapping[str, Any]
    candidate_counts: Mapping[str, int]
    candidates: tuple[Mapping[str, Any], ...]
    pareto: ParetoSummary | None
    best_next: str | None
    cache_stats: Mapping[str, int]
    blockers: tuple[str, ...] = ()
```

- [ ] **Step 1: Write failing phase/resume tests**

```python
def test_run_evaluates_every_legal_mask_and_resumes(tmp_path):
    backends = counting_backends()
    first = run_delta_minimize(config(tmp_path), backends=backends)
    assert first.candidate_counts == {"legal": 4, "viable": 4, "complete": 4}
    assert backends.score_calls == 4
    second = run_delta_minimize(config(tmp_path), backends=backends)
    assert second.to_dict() == first.to_dict()
    assert backends.score_calls == 4


def test_one_incomplete_viable_mask_makes_whole_result_incomplete(tmp_path):
    result = run_delta_minimize(config(tmp_path), backends=backends_missing_inspect_for(mask=2))
    assert result.status == "incomplete"
    assert result.exact_four_axis is False
    assert result.pareto is None
```

- [ ] **Step 2: Implement ordered resumable phases**

```python
PARSER_SCHEMA_HASH = "opcode.v1+color.v1+objobjects.v1+stack-homes.v1"


def _build_evaluation_config(config, objective, store):
    target_path = store.write_color_target(objective.target_spec)
    return CandidateEvaluationConfig(
        melee_root=config.melee_root,
        function=config.function,
        cflags_from=config.cflags_from,
        target_path=target_path,
        output_dir=config.out_dir / "candidates",
        include_objobjects=config.include_objobjects,
    )


def _build_run_provenance(config, objective, parents):
    return {
        "cflags_hash": parents.cflags_hash,
        "compiler_fingerprint": parents.compiler_fingerprint,
        "expected_object_hash": parents.expected_object_hash,
        "objective_manifest_hash": hashlib.sha256(
            json.dumps(objective.to_dict(), sort_keys=True).encode()
        ).hexdigest(),
        "parser_schema_hash": PARSER_SCHEMA_HASH,
        "inspector_version": parents.inspector_version,
    }


def run_delta_minimize(config: DeltaMinimizeConfig, *, backends=None):
    store = DeltaRunStore(config.out_dir)
    parents = _capture_parent_evidence(config, store, backends)
    objective = _load_or_infer_objective(config, parents, store)
    store.bind_provenance(_build_run_provenance(config, objective, parents))
    manifest = _load_or_extract_manifest(config, store)
    masks = enumerate_legal_masks(manifest, max_candidates=config.max_candidates)
    candidates = _materialize_candidates(config, manifest, masks, store)
    evaluation = _build_evaluation_config(config, objective, store)
    raw = [capture_candidate(c, evaluation, backends=backends, store=store) for c in candidates]
    profiles = [profile_candidate(row, objective) for row in raw]
    if any(p.viable and not p.complete for p in profiles):
        return _write_incomplete_result(config, objective, manifest, profiles, store)
    pareto = reduce_pareto(profiles, atom_count=len(manifest.atoms))
    return _write_completed_result(config, objective, manifest, profiles, pareto, store)
```

Write `objective-manifest.json`, `delta-manifest.json`, candidate ledger, and `result.json` atomically after each phase. Do not publish `pareto` for an incomplete run.

- [ ] **Step 3: Run orchestration tests**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_run.py -q`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/melee-agent/src/search/delta_minimize tools/melee-agent/tests/search/delta_minimize/test_run.py
git commit -m "feat: orchestrate resumable delta search"
```

### Task 12: CLI and result rendering

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/render.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/__init__.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_cli.py`
- Create: `tools/melee-agent/tests/golden/debug_cli_help/debug__search__delta-minimize.txt`

**Interfaces:**
- Produces: `render_delta_minimize_text(result)`, `parse_donor_overrides(values)`, Typer command.
- Consumes: `DeltaMinimizeConfig`, `run_delta_minimize()`, and `DeltaMinimizeResult` from Task 11.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_delta_minimize_cli_passes_options(monkeypatch, tmp_path):
    monkeypatch.setattr(search_cli, "run_delta_minimize", fake_run)
    result = CliRunner().invoke(search_app, [
        "delta-minimize", "--function", "draw", "--left", str(LEFT),
        "--right", str(RIGHT), "--out-dir", str(tmp_path),
        "--donor", "color=left", "--json",
    ])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "frontier"


def test_invalid_donor_axis_is_usage_error():
    result = CliRunner().invoke(search_app, [
        "delta-minimize", "--function", "draw", "--left", str(LEFT),
        "--right", str(RIGHT), "--donor", "opcode=left",
    ])
    assert result.exit_code == 2
```

- [ ] **Step 2: Register thin Typer wiring and renderer**

```python
@search_app.command("delta-minimize")
def delta_minimize_cmd(
    function: Annotated[str, typer.Option("--function", "-f")],
    left: Annotated[Path, typer.Option("--left")],
    right: Annotated[Path, typer.Option("--right")],
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("build/delta-minimize"),
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 64,
    target: Annotated[Path | None, typer.Option("--target")] = None,
    donor: Annotated[list[str] | None, typer.Option("--donor")] = None,
    objobjects: Annotated[bool, typer.Option("--objobjects/--no-objobjects")] = True,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    donor_overrides = parse_donor_overrides(donor or [])
    melee_root = _compute_melee_root()
    resolved_left = _resolve_source_file(left, melee_root=melee_root)
    resolved_right = _resolve_source_file(right, melee_root=melee_root)
    assert resolved_left is not None and resolved_right is not None
    cflags_from = _resolve_structure_source_file(function, None, melee_root=melee_root)
    config = DeltaMinimizeConfig(
        function=function,
        left=resolved_left,
        right=resolved_right,
        out_dir=(out_dir if out_dir.is_absolute() else melee_root / out_dir).resolve(),
        max_candidates=max_candidates,
        target_path=target.resolve() if target else None,
        donor_overrides=donor_overrides,
        include_objobjects=objobjects,
        melee_root=melee_root,
        cflags_from=cflags_from,
    )
    result = run_delta_minimize(config)
    typer.echo(json.dumps(result.to_dict(), indent=2) if json_out else render_delta_minimize_text(result))
    if result.status == "incomplete":
        raise typer.Exit(4)
```

Parse only `color`, `objobjects`, and `stack-homes` donor axes. Usage/ambiguity/budget errors exit 2; incomplete infrastructure exits 4; completed statuses exit 0.

- [ ] **Step 3: Generate and verify CLI help golden**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_cli.py tests/test_debug_cli_help_golden.py -q`

Expected: initial golden mismatch, then PASS after saving the exact 80-column help output to the new golden file.

- [ ] **Step 4: Run CLI tests and commit**

Run: `cd tools/melee-agent && pytest tests/search/delta_minimize/test_cli.py -q`

Expected: PASS.

```bash
git add tools/melee-agent/src/search/delta_minimize tools/melee-agent/src/search/cli tools/melee-agent/tests
git commit -m "feat: add two-frontier delta minimizer CLI"
```

### Task 13: End-to-end fixture, regression suite, and real acceptance

**Files:**
- Create: `tools/melee-agent/tests/fixtures/delta_minimize/left.c`
- Create: `tools/melee-agent/tests/fixtures/delta_minimize/right.c`
- Create: `tools/melee-agent/tests/fixtures/delta_minimize/evidence/*.json`
- Create: `tools/melee-agent/tests/fixtures/delta_minimize/evidence/*.pcdump.txt`
- Create: `tools/melee-agent/tests/fixtures/delta_minimize/evidence/*.inspect.txt`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_integration.py`

**Interfaces:**
- Produces a hermetic four-mask wrapper/direct regression and a recorded real-case result.
- Consumes the public CLI only.

- [ ] **Step 1: Add the compact wrapper/direct fixture and failing end-to-end test**

```python
def test_wrapper_direct_fixture_has_exact_reproducible_frontier(tmp_path):
    result = run_fixture_cli(tmp_path, objobjects=True)
    assert result["status"] in {"matched", "joint-zero", "frontier"}
    assert result["exact_four_axis"] is True
    assert result["candidate_counts"]["legal"] == 4
    assert set(result["pareto"]["candidate_ids"]) == {"mask-01", "mask-10"}
    assert result["pareto"]["groups"][0]["minimal_from_left"]
    assert result["pareto"]["groups"][0]["minimal_from_right"]
```

The fixture must model the fighter-header trade: identical opcode graphs, left better coloring/ObjObjects, right exact stack homes, and two semantically coupled helper/call delta atoms.

- [ ] **Step 2: Run the full focused suite**

Run:

```bash
cd tools/melee-agent
pytest tests/search/delta_minimize \
  tests/test_opcode_graph.py \
  tests/test_colorgraph_profile.py \
  tests/test_objobject_profile.py \
  tests/test_stack_home_profile.py \
  tests/test_delta_score_source_evidence.py \
  tests/test_mwcc_debug_inspect_parser.py -q
```

Expected: PASS.

- [ ] **Step 3: Run adjacent regression suites**

Run:

```bash
cd tools/melee-agent
pytest tests/search/test_cli_smoke.py \
  tests/search/test_store.py \
  tests/search/test_structure.py \
  tests/search/directed \
  tests/test_frame_reservations.py \
  tests/test_stack_slot_bridge.py \
  tests/test_mwcc_debug_diff_capture.py -q
```

Expected: PASS.

- [ ] **Step 4: Recover the wrapper frontier and run the real command**

Run from the matcher worktree:

```bash
melee-agent scratch recover-best mnDiagram_DrawFighterHeaders \
  --output build/delta-minimize/fighter-wrapper.c

cd tools/melee-agent
python -m src.cli debug search delta-minimize \
  --function mnDiagram_DrawFighterHeaders \
  --left ../../build/delta-minimize/fighter-wrapper.c \
  --right /Users/mike/.codex/worktrees/eeff/melee/src/melee/mn/mndiagram.c \
  --target ../../build/delta-minimize/fighter-role-target-v2.yaml \
  --donor color=left \
  --donor stack-homes=right \
  --out-dir ../../build/delta-minimize/fighter-real \
  --max-candidates 64 \
  --json
```

`fighter-role-target-v2.yaml` is the reviewed v2 target bound to both retained
source and pcdump hashes, with identity bindings for canonical IGs 64 and 78.
The explicit donor selections preserve the reviewed left allocator target and
the expected-object-backed right stack-home reference used for acceptance.
Keep that target, the frozen parent sources, and retained pcdumps untracked.

Expected: exit 0 with `status` equal to `matched`, `joint-zero`, or `frontier`;
`exact_four_axis: true`; every viable candidate complete and carrying a proven
parent or structural-namespace mapping; both endpoints byte-exact; every Pareto
row linked to retained source, pcdump, inspect snapshot, and stack/color
evidence; and no `ambiguous-color-target`. If any viable mask lacks a proven
mapping, exact frontier publication must remain blocked rather than guessing
from raw IG equality.

- [ ] **Step 5: Verify the repository build**

Run from repository root: `python configure.py && ninja`

Expected: exit 0.

- [ ] **Step 6: Commit fixtures and any final integration corrections**

```bash
git add tools/melee-agent/tests/fixtures/delta_minimize tools/melee-agent/tests/search/delta_minimize
git commit -m "test: cover fighter delta minimization"
```

- [ ] **Step 7: Inspect final history and worktree**

Run: `git status --short --branch && git log --oneline -12`

Expected: clean worktree; one focused commit per task; no unrelated files.
