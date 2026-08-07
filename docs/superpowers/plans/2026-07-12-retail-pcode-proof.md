# Retail PCode Whole-PE Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce, live-validate, promote, and merge one independently auditable retail GC/1.2.5n ObjObject/PCode lifetime proof driven by a deterministic bounded raw whole-PE analysis.

**Architecture:** A strict PE32/x86 parser feeds a deterministic least-reachability raw CFG, finite computed-target fixed point, and exact-hashed unreachable-executable-residue certificate. A separate interprocedural abstract interpreter extends those control-target facts to classify lifecycle, field mutation, rewrite, and emission sites; opcode analysis produces all 468 constructor/layout rules; a canonical proof digest binds a canonical runtime-hook manifest. Existing map and PCode probes install that exact manifest, capture gap-free lifecycle and PCode events, and grant capability only after exact static, hook, lineage, code-mapping, and four-probe gates agree.

**Tech Stack:** Python 3.11, Capstone 5.x, RFC 8785 0.1.4, pytest, Ghidra 12 headless cross-checks, retrowin32/gdb, JSON/JSONL, Ruff, Ninja.

## Global Constraints

- The compiler executable SHA-256 is exactly `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
- The proof schema remains the unmerged `mwcc-retro-lifetime-proof.v1`, amended in place; mode is exactly `allocation-generation`; basis is exactly `exhaustive-static-callgraph-and-disassembly`.
- The proof ID is exactly `gc-1.2.5n-backend-entity-allocation-trace.v1`.
- Do not weaken a validator, invent an address/site/opcode/register range/constructor semantic, or substitute bounded dynamic survival for exhaustive static proof.
- Every relevant unresolved control-flow, value-flow, constructor, site, capture-semantic, or emission path fails closed. A diagnostic 29/30 publication split may be retained as evidence, but no accepted lifetime bundle may contain an `unresolved-control-target`; final publication requires an empty unresolved inventory.
- Analysis is deterministic and explicitly bounded. Hitting a cap is an error, never truncation or widening to a trusted result.
- Ghidra is a cross-check, not authoritative function ownership.
- Extend `debug retro probe-backend-map` and `probe-backend-pcode`; add no new top-level CLI command.
- Generated compiler binaries, Ghidra projects, full CFG artifacts, candidate tables, and live probe output remain ignored.
- Do not modify `/Users/mike/.codex/worktrees/b8fa/melee`, merge its full stack, or port unrelated causal-differencer/Producer Task 9/Task 10 work.
- Preserve the exact compiler/proof/digest registry binding fixed at `3d3c3fbbc`.
- Keep installed `instrumentation_proofs=[]`, `pcode_instrumentation.validated=false`, and installed capabilities empty until both deterministic static runs and all four live gates pass.
- The proof digest binds the RFC 8785 digest of `mwcc-retro-runtime-hooks.v1`; the unchanged promotion registry tuple therefore binds every runtime breakpoint/capture semantic.
- Every hook-plan site is installed exactly. `per-run` sites hit in every live probe and every `probe-union` site hits in at least one of the four-run union; no optional/install-only policy exists.
- Fix and re-review every Critical or Important task or broad-review finding before proceeding.
- A `ProducerCheckpointIncomplete` refusal is resumable progress only when its parsed counters prove `0 < completed_this_run <= 2048`, valid discovered/validated/pending relationships, and the expected checkpoint directory. Reinvoke that same output root so its producer checkpoints and rejection ledgers advance; never restart merely because one positive-progress invocation exhausted the query budget. A zero-progress or malformed refusal fails immediately. The exception text reports `completed_this_run` only on a nonzero checkpoint refusal. A status-zero invocation is silent about that counter and already proves no new or pending checkpoint work remained; accept it only after `resolve_lifetime_bundle` validates the published generation.
- Resolve every candidate, proof, hook-manifest, and report path through `resolve_lifetime_bundle(...).path(...)` or `canonical_files()`. The canonical files live only in the immutable generation selected by `CURRENT`; a top-level `runN/<member>` path is never authoritative.

## Completed reviewed foundation

Commits `1b057f747..3d3c3fbbc` already provide the proof/registry trust substrate, object/frame capture, same-run PCode lineage, fail-closed PCode diagnostics, and independent registry binding. The clean handoff baseline is freshly verified at 439 focused tests. Do not re-dispatch or rewrite this foundation; migrate it through the tasks below.

The approved design is `docs/superpowers/specs/2026-07-12-mwcc-retro-whole-pe-proof-design.md` at commit `44137746c`.

## Disposable merge-rehearsal baseline

The read-only rehearsal
`git merge-tree --write-tree --messages master 7abd5f7a2` was run before the
completion-path amendment. Its merge base is `25aec205a`, and it reports 20
conflicts that must be resolved rather than discovered during the real merge:

- ten add/add conflicts: the `pcode_lineage` fixtures
  `duplicate_output.json`, `fresh_clone_id.json`, `missing_emission.json`,
  `self_parent.json`, and `wrong_machine_register.json`,
  `test_retro_backend_instrumentation_proof.py`,
  `test_retro_backend_object_snapshot.py`,
  `test_retro_backend_pcode_lineage.py`,
  `backend_instrumentation_proof.py`, and `backend_pcode_lineage.py`;
- ten content conflicts: `src/cli/debug/retro.py`,
  `test_retro_backend_map_evidence.py`,
  `test_retro_backend_pcode_snapshot.py`,
  `test_retro_backend_runtime.py`,
  `test_retro_backend_trace_assembler.py`, `test_retro_struct_map.py`,
  `backend_map_probe_hook.py`, `backend_onepass_trace_hook.py`,
  `backend_trace_assembler.py`, and `struct_map.py`.

Repeat the read-only merge-tree rehearsal after code/review freeze, then perform
the resolved merge and its tests in a disposable worktree before touching
`/Users/mike/code/melee`. Rehearsal work must never mutate the main checkout or
the canonical issue worktree.

## File structure

- `tools/mwcc_retro/pe.py`: strict PE32/x86 parsing and exact bounded reads only.
- `tools/mwcc_retro/x86_cfg.py`: compiler-agnostic deterministic x86 instruction ownership, blocks, edges, calls, and jump tables.
- `tools/mwcc_retro/backend_abstract_values.py`: finite abstract values, x86 transfer functions, call summaries, SCC/fixed-point engine.
- `tools/mwcc_retro/backend_lifetime_audit.py`: MWCC-specific allocation/type/field/unlink/mutation/rewrite/emission classification and Ghidra cross-checks.
- `tools/mwcc_retro/backend_opcode_layout.py`: exact 468-row metadata, generic/custom/variadic constructor and register-domain analysis.
- `tools/mwcc_retro/backend_lifetime_proof.py`: canonical audit publication, proof/manifest generation, two-run comparison, candidate-table assembly.
- `tools/mwcc_retro/backend_runtime_hook_manifest.py`: closed manifest validation, canonical digesting, proof/manifest bijection.
- `tools/mwcc_retro/backend_runtime_instrumentation.py`: gdb-side exact-plan installer, lifecycle generations, atomic capture helpers.
- `tools/mwcc_retro/tables/gc_125n_lifetime_proof.json`: tracked exact proof after static review.
- `tools/mwcc_retro/tables/gc_125n_lifetime_hooks.json`: tracked proof-bound runtime manifest after static review.
- `tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java`: Ghidra instruction/call/reference inventory without completeness authority.
- `tools/melee-agent/tests/retro_pe_fixture.py`: synthetic PE32 builder shared only by tests.
- `docs/mwcc-retro-gc125n-lifetime-proof.md`: generated facts plus human completeness/live evidence.

---

### Task 1: Correct v1 schema and preserve exact raw PCodeArg state

**Files:**
- Create: `tools/mwcc_retro/backend_runtime_hook_manifest.py`
- Modify: `tools/mwcc_retro/backend_instrumentation_proof.py`
- Modify: `tools/mwcc_retro/backend_pcode_lineage.py`
- Modify: `tools/mwcc_retro/backend_pcode_snapshot.py`
- Modify: `tools/mwcc_retro/backend_events.py`
- Modify: `tools/mwcc_retro/backend_trace_assembler.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Modify: `tools/mwcc_retro/struct_map.py`
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Modify: `tools/melee-agent/tests/test_retro_backend_instrumentation_proof.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_pcode_lineage.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_pcode_snapshot.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_events.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_trace_assembler.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_map_evidence.py`
- Modify: `tools/melee-agent/tests/test_retro_struct_map.py`
- Modify: `tools/melee-agent/tests/fixtures/retro/pcode_lineage/*.json`

**Interfaces:**
- Produces `expand_operand_descriptors(proof, opcode_id, arg_count) -> tuple[ExpandedOperandDescriptor, ...]`.
- Produces `classify_operand(descriptor, capture_stage, raw_flags, raw_value) -> OperandState` with exact-one matching.
- Produces `runtime_hook_manifest_sha256(payload) -> str` and `validate_runtime_hook_manifest(payload, proof) -> tuple[str, ...]`.
- Preserves public `InstrumentationProof`, `proof_sha256`, `validate_proof_shape`, `validate_embedded_proof`, `trusted_proof_from_trace`, and `validate_pcode_lineage` entrypoints.
- Adds `runtime_hook_manifest_sha256` to the proof root without changing the registry row shape.

- [ ] **Step 1: Add RED proof/manifest schema tests**

Add helpers that build all 468 opcode rows and descriptors, plus focused tests for missing ID 467, duplicate mnemonic, custom opcode without constructor addresses, `#` counting, `Y != 8`, non-final `V`, negative/leftover expansion, vector/special/CR coupling, wrong stage, missing/overlapping state rules, malformed raw bytes, altered manifest digest, and hostile mappings.

```python
def test_addi_stage_and_u16_value_break_old_rule_collision():
    proof = proof_payload_with_addi_rules()
    before = classify_operand(proof_descriptor(proof, 63, 0), "allocator_input", 2, 34)
    after = classify_operand(proof_descriptor(proof, 63, 0), "code_emission", 2, 0)
    assert (before.allocation_state, before.virtual, before.physical_register) == (
        "virtual", 34, None
    )
    assert (after.allocation_state, after.virtual, after.physical_register) == (
        "physical", None, 0
    )


def test_proof_digest_binds_runtime_hook_manifest():
    proof, manifest = valid_proof_and_manifest()
    manifest["sites"][0]["capture_sources"][0]["byte_width"] = 2
    assert "runtime hook manifest digest differs from proof" in validate_runtime_hook_manifest(
        manifest, proof
    )
```

- [ ] **Step 2: Run the RED tests**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_pcode_snapshot.py \
  tests/test_retro_backend_events.py \
  tests/test_retro_backend_trace_assembler.py \
  tests/test_retro_backend_map_evidence.py \
  tests/test_retro_struct_map.py -x
```

Expected: FAIL because the old proof accepts only `{opcode_id,mnemonic}`, the old rule key has no stage/value/expansion, and the manifest API does not exist.

- [ ] **Step 3: Implement closed opcode/descriptor/state validation**

Use frozen values with these exact public shapes:

```python
@dataclass(frozen=True, slots=True)
class ExpandedOperandDescriptor:
    operand_index: int
    descriptor_index: int
    raw_arg_kind_id: int
    role: str
    register_form: str
    class_id: int | None
    virtual_kind: str | None
    state_rules: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class OperandState:
    allocation_state: str
    virtual: int | None
    physical_register: int | None
```

Require opcode IDs exactly `list(range(468))`, unique nonempty mnemonics, exact constructor coupling, contiguous descriptor indices, exact format reproduction, final-only remaining expansion, finite flag-predicate overlap checks, unsigned 16-bit bounds, and canonical nested ordering. `none` has no state rules; special/CR only `non-allocator`; GPR/FPR/vector use exact class/form/kind coupling.

- [ ] **Step 4: Implement and bind the closed runtime-hook manifest**

Validate exact root/site/breakpoint/capture-source fields from the design. Recompute instruction byte digests, reject generic expressions, require proof site and manifest rows to match by `(site_id, family, proof_address)`, and require proof `runtime_hook_manifest_sha256` to equal RFC 8785 canonical manifest SHA-256.

- [ ] **Step 5: Preserve and independently decode all raw operand bytes**

Keep `raw_arg_kind_id`, `raw_register_flags`, `raw_register_value`, `raw_payload_hex`, and `raw_payload_sha256` through `backend_events` and `backend_trace_assembler`. Validate 12 exact bytes and recompute kind/flags/little-endian u16/digest in lineage. Replace `allocation_requirement` with `allocation_state`; add `register_form` and nullable class/virtual/physical coupling. Count virtual, physical, and non-allocator registers separately.

- [ ] **Step 6: Enable the proven raw layout without promotion**

Add `PCode.args=0x1C`, `PCodeArg.kind=0`, `register_flags=1`, `payload=2`, and `size=0x0C` to `gc_125n.json` with exact retained disassembly provenance. Keep `instrumentation_proofs=[]`, gate `validated=false`, null proof tuple, empty site arrays, and empty installed capability.

- [ ] **Step 7: Migrate fixtures and run GREEN verification**

Run the Step 2 suite, then the exact focused foundation command:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_frame_state.py \
  tests/test_retro_backend_object_snapshot.py \
  tests/test_retro_backend_ig_snapshot.py \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_pcode_snapshot.py \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_map_evidence.py
```

The pristine baseline collected 439 tests; after this task the count may increase. Expected: every collected test passes with no warnings and installed registry/gate assertions remain empty/false.

- [ ] **Step 8: Static checks and commit**

Run scoped Ruff on changed Python files, `python -m py_compile` on production files, `python -m json.tool` on changed fixtures/table, and `git diff --check`.

Commit: `feat: correct retail pcode proof state schema`

---

### Task 2: Make the PE reader a strict exact-hash proof boundary

**Files:**
- Modify: `tools/mwcc_retro/pe.py`
- Create: `tools/melee-agent/tests/retro_pe_fixture.py`
- Modify: `tools/melee-agent/tests/test_retro_pe.py`

**Interfaces:**
- Produces `load(path, *, expected_sha256=None, require_pe32_i386=False) -> Image`.
- `Image` exposes `sha256`, `machine`, `optional_magic`, `entrypoint`, `directories`, `imports`, `exports`, `relocations`, and executable ranges.
- `Image.read(va, size)` returns exactly `size` bytes or raises `ValueError`.

- [ ] **Step 1: Add RED malformed-PE and exact-hash tests**

```python
@pytest.mark.parametrize(
    "mutation, message",
    [
        ("wrong_machine", "PE machine must be i386"),
        ("wrong_magic", "optional header must be PE32"),
        ("overlap_raw", "overlapping PE raw sections"),
        ("overlap_virtual", "overlapping PE virtual sections"),
        ("truncated_directory", "truncated PE data directory"),
    ],
)
def test_strict_pe_rejects_malformed_images(tmp_path, mutation, message):
    path = write_synthetic_pe(tmp_path, mutation=mutation)
    with pytest.raises(ValueError, match=message):
        pe.load(path, require_pe32_i386=True)


def test_read_rejects_short_cross_section_access(strict_image):
    with pytest.raises(ValueError, match="read is not wholly mapped"):
        strict_image.read(strict_image.sections[0].va + strict_image.sections[0].raw_size - 1, 2)
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_pe.py -x
```

Expected: FAIL because the strict parameters and metadata do not exist and current reads can return short bytes.

- [ ] **Step 3: Implement strict parsing**

Use checked `struct.unpack_from` helpers, validate every offset/size before access, parse section characteristics and data directories, and reject raw/virtual overlaps. Parse exports, imports/IAT, and base relocations into frozen canonically sorted tuples. Hash bytes once and compare the optional exact lowercase digest before exposing analysis data.

- [ ] **Step 4: Verify the real compiler identity read-only**

Add a skip-if-missing integration test requiring SHA, i386/PE32, image base `0x00400000`, entry `0x00401000`, and `.text` executable bounds derived from headers. Do not copy the compiler into fixtures.

- [ ] **Step 5: Run GREEN/static checks and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_pe.py tests/test_retro_backend_discovery.py
cd ../..
python -m ruff check tools/mwcc_retro/pe.py tools/melee-agent/tests/retro_pe_fixture.py \
  tools/melee-agent/tests/test_retro_pe.py
python -m py_compile tools/mwcc_retro/pe.py
git diff --check
```

Commit: `feat: validate exact PE boundary for retail audit`

---

### Task 3: Recover deterministic direct x86 CFG and instruction ownership

**Files:**
- Create: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`
- Create: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Produces `AnalysisLimits.for_image(image) -> AnalysisLimits` with structural caps.
- Produces `build_seed_inventory(image, audit_anchors) -> SeedInventory`.
- Produces `recover_cfg(image, seeds, limits) -> RawCfg`.
- `SeedInventory` records authoritative entrypoint/export, strictly parsed loader/CRT/unwind callback, and exact-byte audit-anchor roots plus their byte provenance. Relocation-backed executable pointers and callback initializers enter only through proved PE structure or reachable registration/data flow; direct and finite targets are derived closure facts, not syntax roots.
- `RawCfg` contains the canonical authoritative-root inventory, explicit `is_function` entries, instructions, blocks, edges, direct calls, raw E8 candidates, data regions, ownership diagnostics, caps, and high-water marks. Task 4 adds the post-closure unreachable-executable-residue certificate.

Use exact default caps:

```python
@dataclass(frozen=True, slots=True)
class AnalysisLimits:
    max_instructions: int          # sum executable raw bytes
    max_blocks: int                # sum executable raw bytes
    max_edges: int                 # 8 * sum executable raw bytes
    max_jump_tables: int = 65_536
    max_jump_table_entries: int = 524_288
    max_functions: int = 65_536
    max_finite_targets: int = 65_536
    max_finite_values: int = 8_192
    max_states_per_block: int = 256
    max_contexts_per_entry: int = 256
    max_scc_iterations: int = 65_536
    max_summary_iterations: int = 65_536
    max_fixpoint_updates: int = 8_000_000
```

Every cap hit raises `AnalysisLimitError` with configured limit and observed high-water value.

- [ ] **Step 1: Add RED CFG fixtures/tests**

Synthetic `.text` includes an entry, export, direct call, fallthrough, conditional branch, return, padding, a relocation-proven executable pointer in a proved initializer, an audit anchor, pointer-referenced data, and embedded fake `E8` bytes. Test every authoritative root category and byte provenance, canonical output under reversed root order, instruction-interior conflicts, unmapped targets, unresolved relocation obligations, and equality-at-cap plus over-cap for every cap. A malformed/unmapped/interior root and an executable relocation or initializer that cannot be classified are unresolved blockers. Add adversarial bytes that decode cleanly after a return and relocation-aligned bytes after zeros; neither is a root or function without authoritative incoming provenance.

```python
def test_seed_order_cannot_change_raw_cfg(synthetic_cfg_image):
    a = recover_cfg(synthetic_cfg_image, (0x401000, 0x401040), limits())
    b = recover_cfg(synthetic_cfg_image, (0x401040, 0x401000), limits())
    assert a.to_dict() == b.to_dict()


def test_embedded_e8_is_explained_as_data_not_call(synthetic_cfg_image):
    cfg = recover_cfg(synthetic_cfg_image, (0x401000,), limits())
    row = next(row for row in cfg.raw_e8_candidates if row.address == 0x401080)
    assert row.classification == "owned-data"
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py -x
```

Expected: import failure for `x86_cfg`.

- [ ] **Step 3: Implement authoritative roots and direct least-reachability recovery**

Build the initial numeric root set only from the PE entrypoint and exports; strictly parsed, bounded loader/CRT/unwind callbacks; and the closed audited anchors recorded by the design/evidence (`formatoperands`, arena helpers, unlink helper, allocation candidates, mutation/rewrite helpers, final walker/encoder/buffer-write sites). Validate each audit anchor against exact instruction bytes before trusting it and publish its provenance; an anchor is a completeness root, never semantic proof. A relocation-backed executable pointer is admitted only when the containing slot is proved as a code-pointer initializer by a PE-declared structure or later reachable registration/data flow. Decode Capstone x86-32 with detail mode and skip-data disabled. Add reachable fallthrough and every exact direct call/branch target to the numeric heap worklist. Split blocks on targets, calls, conditional/unconditional branches, returns, and indirect transfers. Maintain exact byte ownership and reject overlap/interior targets.

Delete and forbid `relocation-aligned-entry`, `relocation-computed-transfer`, `relocation-inline-data-successor`, `closed-executable-island`, and `closed-aligned-function` as seed/function/code categories, and forbid `terminal-noninstruction-separator` as evidence. Relocation alignment, a successful decode, a zero prefix, a terminal instruction, and a closed-looking byte island never prove code. Independently scan raw executable bytes for valid `E8 rel32` encodings, but never turn a scan hit into a root or edge. Task 4 partitions those hits after control-flow closure. Any authoritative root or executable relocation obligation that is unmapped, interior, ambiguous, or unexplained blocks proof.

- [ ] **Step 4: Implement canonical serialization**

No host path, timestamp, elapsed time, unordered set, or nondeterministic Capstone representation enters digest-bearing output. Sort records by `(address, record_kind, target)` and emit compact UTF-8 JSON lines with a final newline.

- [ ] **Step 5: Run GREEN/static checks and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_x86_cfg.py tests/test_retro_pe.py
cd ../..
python -m ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/retro_pe_fixture.py tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile tools/mwcc_retro/x86_cfg.py
git diff --check
```

Commit: `feat: recover deterministic raw x86 control flow`

---

### Task 4: Close computed flow and cross-check Ghidra without trusting ownership

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Create: `tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java`
- Create: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Create: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_cli.py`

**Interfaces:**
- Adds `JumpTable` with guard address/operator/bound, base, entry width, index range, raw entries, and targets.
- Produces a provenance-bearing context-sensitive `ControlTargetResult` whose finite target sets, terminal external edges, external escapes, and unresolved rows are consumed unchanged by Task 5.
- Produces `compare_ghidra_inventory(cfg, inventory) -> CrosscheckReport`.
- Produces `resolve_static_backend_bundle(out_dir) -> PublishedStaticBundle`; readers never open generation members without this manifest-verifying resolver.
- `probe-backend-map --static-only` transactionally publishes one transitional generation containing `raw-pe-cfg.v1.jsonl`, `raw-ghidra-crosscheck.v1.json`, and `backend-map-candidates.json` after the existing exact-hash `ghidra-setup` prerequisite.

- [ ] **Step 1: Add RED computed-flow and cross-check tests**

Cover absolute and base+index tables, bounded callback sets, missing guard, conflicting width/base, unmapped entry, target outside `.text`, 468-way synthetic dispatch, and a Ghidra inventory missing a raw-owned body. A table domain must come from a reachable guard, finite initializer domain, or finite value set; a contiguous relocation run by itself is never a bound.

Add context-sensitive finite-target fixtures for cdecl arguments and spills/reloads, finite returns through wrappers, globals/BSS registrars, object and descriptor fields, strictly parsed CRT/unwind registrations, and import/IAT terminal edges. An unknown target, a possible internal code pointer escaping through an unmodelled import, or an import return used as a target stays unresolved and blocks. Test that the forbidden Task 3 categories and `terminal-noninstruction-separator` cannot promote the cleanly decodable byte strings `41 42 43 c3` after an owned return or `41 42 43 44 a1 80 20 40 00 c3` after zeros/relocation evidence.

Add residue tests proving the complete executable-byte partition is disjoint, exact-hashed, deterministic, and accepted only after every root, relocation, direct edge, finite target, and external escape is closed with zero potentially internal unresolved transfers and every intersecting Ghidra fact is independently reconciled. Raw `E8` scan hits never seed decoding and are partitioned as reachable instruction, reachable proved data, or unreachable executable residue.

Add provisional-residue/Ghidra reconciliation fixtures for an instruction,
function entry, callback, caller chain, typed flow, data reference, and
executable-pointer reference. Independently decode the exact raw bytes in each
case. A separately proved incoming root/registration must expand and recompute
raw closure; independent PE/control evidence may classify the bytes as
unreachable or non-code; and absence of either proof must block. Assert that a
Ghidra label alone never seeds code and that raw omission alone never proves
unreachability.

```python
def test_guarded_468_way_dispatch_is_recovered(dispatch_image):
    cfg = recover_cfg(dispatch_image, (dispatch_image.entrypoint,), limits())
    table = cfg.jump_table_at(dispatch_image.dispatch_address)
    assert table.index_min == 0
    assert table.index_max == 467
    assert len(table.targets) == 468


def test_missing_ghidra_owner_is_delta_not_raw_failure(raw_cfg, ghidra_inventory):
    report = compare_ghidra_inventory(raw_cfg, ghidra_inventory)
    assert report.raw_only_functions
    assert not report.unresolved_raw_addresses
```

Cross-check fixtures use shared byte-equal sources and independently vary typed
flow successors, computed targets, data references, and executable-pointer
references. A Ghidra-only fact at a shared source, any byte conflict, and every
raw unresolved address block; raw-only facts and ownership deltas remain
reported without granting Ghidra completeness authority. Test that the raw
function-entry inventory contains every canonical row marked
`is_function=true`, independent of its provenance category.

Add exact `formatoperands` RED mutations for entry-to-dispatch reachability,
each of the three dispatch instruction byte strings and their typed edges,
the unsigned bound, every one of the 466 type-3 relocation slots, the two
following exact unrelocated dwords and their rejection, handler/default exit
convergence, an extra/missing reachable return, and an unresolved transfer in
the closure. Store the pre-repair 705 rows once as a canonical frozen
historical fixture with an asserted digest and require every frozen row to
receive one current disposition: resolved internal control, terminal external,
unreachable because its unsound source category was deleted, or current
blocker. The current analyzer neither regenerates nor requires that count. The
skip-if-missing exact-binary integration independently analyzes the current
binary and requires zero current blockers, including fresh rows absent from
the historical fixture.

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_cli.py -x
```

Expected: failures for the forbidden seed reproductions, missing finite-target
closure/residue, incomplete cross-check/format assertions, non-transactional
publication, and a nonzero exact unresolved inventory.

- [ ] **Step 3: Implement the finite control-target fixed point and residue certificate**

Derive table bounds only from reachable dominating guards or other proved finite domains. Record every entry and refuse an unbounded scan; neither a relocation run nor decodability beyond the domain extends a table. Implement the minimal provenance-bearing, context-sensitive fixed point for control targets: cdecl arguments and stack spills/reloads, finite call returns, globals/BSS registrar slots, object/descriptor fields, strictly parsed CRT/unwind records, and imports/IAT as typed terminal external edges. Resolve callbacks through the same engine and iterate roots, decoding, target facts, and ownership monotonically to the least fixed point.

An unknown or import-return value used as a computed target, a possible internal code pointer that escapes to an unmodelled external callee, an initializer without finite use provenance, or any other potentially internal unresolved transfer is a hard blocker. Freeze the first exact pre-repair run's 705 rows and their canonical digest as historical classification coverage only. Do not reproduce, require, or compare a current analyzer count to 705. Account for each frozen row as currently resolved internal control, terminal external, unreachable because its unsound source category was deleted, or a current blocker. Independently require the freshly computed current unresolved inventory to be empty; a fresh row not present in the historical fixture is still a blocker.

Only after that zero-unresolved result and complete root/relocation/direct/finite/external-escape closure, form a provisional residue partition from all remaining executable bytes. Store ordered intervals plus exact bytes/hashes and the complementary reachable ownership hash. Reject overlap, omission, reachability into residue, a changed partition, or any raw `E8` candidate outside the three closed classifications. Step 4 must independently reconcile every intersecting Ghidra fact, recomputing closure when it yields new provenance, before the partition becomes an accepted `unreachable-executable-residue` certificate.

- [ ] **Step 4: Export and compare Ghidra evidence**

The Java script emits every recovered Ghidra instruction with exact bytes, function entry/body range, typed flow successor, computed target, data reference, and executable-pointer reference in numeric order. It asserts the exact program hash. At each shared byte-equal instruction source, Python compares canonical typed sets for all four semantic families. Any Ghidra-only fact at a shared source, byte mismatch, or raw unresolved address blocks. Raw-only facts and missing Ghidra owners are reported without deleting raw facts.

For every Ghidra instruction/function/flow/reference fact intersecting the provisional raw residue, independently verify the exact PE bytes and decode boundaries. Then either derive independent incoming root/control/registration provenance and recompute raw closure, prove from independent PE structures and already closed control facts that the bytes are unreachable or non-code, or block. Ghidra ownership never supplies the independent proof. An unexplained decoded island, callback, function, caller chain, computed target, or reference in residue blocks, and raw omission cannot prove its own unreachability. Report non-shared ownership deltas only after this reconciliation. Build the raw function-entry set from every canonical `RawCfg` row whose `is_function` field is true, not from a hard-coded provenance-category allowlist.

- [ ] **Step 5: Integrate `probe-backend-map --static-only`**

Keep the same command. At this task boundary, extend help/output to publish the transitional `raw-pe-cfg.v1.jsonl`, `raw-ghidra-crosscheck.v1.json`, and existing `backend-map-candidates.json` as one immutable generation. Task 7 replaces the logical transitional member set with the closed nine-file bundle while preserving the same resolver/transaction model. The command must execute in this order: load and exact-hash the PE; recover the bounded least-reachability CFG and zero-unresolved control-target closure; form only a provisional residue partition; invoke the validated Ghidra exporter against the already prepared exact-hash project; parse and compare its numeric inventory; and reconcile every Ghidra fact intersecting residue. Any independently proved new root or edge restarts raw closure, provisional partitioning, and reconciliation until the monotone result is stable. Only then accept the residue certificate and publish. Blocking or unexplained cross-check facts fail; a missing Ghidra owner with consistent raw bytes/flow is reported.

Create a same-filesystem staging directory under the output root and write all three members there. Flush and `fsync` each member; write last a canonical manifest binding the exact member names, sizes, hashes, compiler identity, and schema; flush/`fsync` it and the staging directory; rename the directory to an immutable generation name; and `fsync` the generations parent. Publish a flushed/`fsync`ed temporary `CURRENT` pointer containing the generation name and manifest hash with one atomic replace, then `fsync` the output root. `resolve_static_backend_bundle` follows only `CURRENT` and validates the pointer, manifest, and all members before returning any of them. On failure or restart, an old generation remains wholly visible and partial/orphan generations are ignored or cleaned; mixed generations are impossible.

The production path is branch-local and executable without relying on the installed editable entry point:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
cd "$ROOT"
DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
  melee-agent debug retro ghidra-setup \
  --melee-root "$ROOT" \
  --project-dir "$ROOT/tools/mwcc_debug/ghidra_project"
cd "$ROOT/tools/melee-agent"
DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
  python -m src.cli debug retro probe-backend-map \
  "$ROOT/src/melee/mn/mndiagram.c" \
  -f mnDiagram_DrawFighterHeaders \
  --static-only \
  --melee-root "$ROOT" \
  -O "$ROOT/build/mwcc_retro/gc125n-proof/static-smoke"
```

`probe-backend-map --static-only` invokes `tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java` through the validated project and writes its numeric inventory only inside a newly created `tempfile.TemporaryDirectory` outside the output directory. It consumes that exact temporary file before building the cross-check generation member, which records the canonical inventory digest, and deletes the temporary directory on both success and failure. It refuses a stale, missing, differently hashed, or manually substituted inventory. The transient exporter inventory is never a published artifact. Add failure injection at every member write/fsync, manifest write/fsync, directory rename/fsync, and `CURRENT` replace/fsync boundary plus restart tests proving the resolver returns the whole previous or whole next generation and never partial output.

- [ ] **Step 6: Run the exact compiler regression**

Require raw recovery to start at `formatoperands` entry `0x004C4BF0` and reach the exact instruction bytes `81fad1010000` at `0x004C4C01`, `0f8733120000` at `0x004C4C07`, and `ff24957c285600` at `0x004C4C0D`, with the exact compare/fallthrough/default/table edges. Derive the unsigned domain `0..465`, table base `0x0056287C`, and all 466 entries. Require every slot to have a type-3 relocation and an executable target; assert the exact 466-entry byte digest `575e165f8bfb3a01076871267f1fed9f5844219f9de565ff0941fd8b312afac7`; and require the next dwords at `0x00562FC4` and `0x00562FC8` to be the exact unrelocated non-code values `0x2d` and `0x4228`, rejected as entries. Prove every distinct handler and the default path converge through the shared exit, exactly one return is reachable from the function entry, and the entire closure has zero unresolved transfers.

Keep the independent 468-way synthetic dispatch test as a generic boundary case. The separate opcode metadata proof still covers IDs `0..467`; IDs 466 `PENTRY` and 467 `PEXIT` are zero-encoding pseudo-ops whose final-list survival/elimination remains a Task 7 obligation. Reproduce or explicitly explain each retained lower-bound pair as a separately named audit assertion: 3,187 recovered internal Ghidra functions and 27,020 direct calls in their bodies; 1,861 raw/Ghidra-union arena calls versus 1,825 within recovered bodies; 962 raw selected-PCode-helper calls versus 773 within recovered bodies; and 102 raw unlink-helper calls versus 59 within recovered bodies. These are historical regression cross-checks, never analyzer completeness truth or hard-coded acceptance counts.

- [ ] **Step 7: Run GREEN/static checks and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_cli.py tests/test_ghidra_mwcc_setup.py \
  tests/test_mwcc_ghidra_setup_script.py
cd ../..
python -m ruff check tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py tools/melee-agent/src/cli/debug/retro.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_backend_cli.py
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py tools/melee-agent/src/cli/debug/retro.py
git diff --check
```

The `test_mwcc_ghidra_setup_script.py` run is the Java/headless source sanity gate; the exact compiler regression in Step 6 is the integration gate.

Commit: `feat: close computed retail compiler control flow`

---

### Task 4A: Close the independent `0x4b1f95` ESP-slot binding

**Execution order:** This is a late Task 4 completion addendum, not permission
to replay already developed Tasks 5/6 as accepted proof. Run it after the
companion publication plan has retained its intermediate 29/30 diagnostic, as
specified by the controller gates at the end of this plan.

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify if the accepted audit projection changes:
  `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`
- Update: `docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md`

**Interfaces:**
- Extends the generic finite-control analysis with an exact ESP-relative slot
  binding proof. It must bind a value stored or pushed through a stack slot to
  the same receiver/argument identity at the indirect transfer across every
  reachable predecessor, stack adjustment, spill/reload, and call effect.
- Produces the stable `esp-slot-binding-domain` jump-table provenance only when
  the complete predecessor domain proves the exact finite index set. It is not
  an object-tag lifecycle-v6 or publication-noninterference exception.
- Consumes the companion return-path plan's retained 29/30 diagnostic, then
  returns control to that plan for the final zero-unresolved publication run.

- [ ] **Step 1: Preserve the intermediate 29/30 diagnostic and add RED tests**

First retain the companion plan's diagnostic proving that the 29 lifecycle
calls are independently admitted and that `0x4b1f95` remains the sole
`index=75` computed-flow blocker with no publication-certificate provenance.
This is diagnostic evidence only: `backend_lifetime_proof._collect_unresolved`
must continue rejecting it, and no `CURRENT` publication may be claimed from
that invocation.

Add generic fixtures covering an indirect table index that is stored through
an ESP-relative local, reloaded after balanced stack adjustments, and passed
through a receiver/argument binding. Add hostile variants for one predecessor
with a different value, an aliased/partially overwritten slot, an unbalanced
stack delta, an intervening unknown call effect, a mismatched receiver, an
open predecessor, and an out-of-domain value. Assert that each hostile variant
remains unresolved and that no fixture uses a retail address allowlist or a
publication certificate.

- [ ] **Step 2: Implement the generic ESP-slot binding proof**

Reuse the existing stack-state, exact-definition, argument-binding, and finite
domain machinery. Normalize each slot by the proven ESP state at the write and
read, require one unchanged four-byte identity across the complete reachable
predecessor set, and reject partial writes, aliasing, unknown call mutation,
or any unknown stack state. Feed the resulting exact finite domain through the
normal indexed-table relocation/executable-target checks. Do not special-case
`0x4b1f95`, `0x560648`, index 75, the compiler hash, or the publication
certificate in the generic resolver.

- [ ] **Step 3: Run the exact compiler acceptance**

Rerun the companion plan's exact root checks and focused static command in the
same retained `return-path-publication-v6` root. The command may resume existing
v27/v6 producer checkpoints and ledgers. Repeat only across expected nonzero
`ProducerCheckpointIncomplete` refusals whose parsed `completed_this_run` is
positive. A zero-progress refusal is a hard failure. The first status-zero
invocation is the zero-new completion pass; resolve its resulting bundle
through `resolve_lifetime_bundle` and require:

- zero `unresolved-control-target` rows globally;
- exactly one `jump-table` row at `0x004b1f95`, with flow kind `call`, base
  `0x00560648`, domain `0..74`, and guard operator
  `esp-slot-binding-domain`;
- no nested integer or hexadecimal-string occurrence tying `0x004b1f95` to a
  `return-path-publication-noninterference` row; and
- all table entries still pass the ordinary relocation and executable-target
  checks, with no acceptance-rule weakening.

- [ ] **Step 4: Run focused checks, review, and commit**

Run the Task 4 focused CFG/audit/CLI suites, scoped Ruff, py_compile, and
`git diff --check`. Review the genericity and the exact accepted JSONL before
committing.

Commit: `feat(mwcc-retro): prove esp-slot control bindings`

---

### Task 5: Add bounded interprocedural values, types, and call summaries

**Files:**
- Create: `tools/mwcc_retro/backend_abstract_values.py`
- Create: `tools/melee-agent/tests/test_retro_backend_abstract_values.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`

**Interfaces:**
- Produces frozen `AbstractValue`, `MachineState`, `FunctionSummary`, and `AnalysisResult`.
- Produces `analyze_values(image, cfg, control_targets, roots, limits) -> AnalysisResult`, where `control_targets` is the exact accepted Task 4 fixed-point result.
- Unknown values retain exact origin/reason and cannot silently enter proof-relevant outputs.
- Task 5 reuses every Task 4 context, target, terminal-import, external-escape, and provenance fact, extends the lattice semantically, and may add facts monotonically; it cannot discard a Task 4 blocker or rerun a weaker independent target analysis.

- [ ] **Step 1: Add RED lattice/transfer/fixpoint tests**

Cover exact/finite/affine/null/image/typed pointers, stack arguments, cdecl returns, wrapper calls, globals, loops/SCC convergence, unsupported instructions on relevant versus irrelevant slices, finite-set/state/update cap failures, deterministic summary ordering, and lossless import of every Task 4 control-target fact. A semantic refinement that changes a finite control target forces CFG closure/residue regeneration before proof continues.

```python
def test_affine_pcode_allocation_survives_wrapper_call(pcode_wrapper_cfg):
    result = analyze_values(pcode_wrapper_cfg.image, pcode_wrapper_cfg.cfg, roots(), limits())
    call = result.call_at(pcode_wrapper_cfg.allocator_call)
    assert call.argument(0).affine == (0x28, 0x0C, "arg_count")
    assert call.return_value.pointer_type == "pcode"


def test_relevant_unknown_is_blocker(unsupported_store_cfg):
    result = analyze_values(unsupported_store_cfg.image, unsupported_store_cfg.cfg, roots(), limits())
    assert result.proof_ready is False
    assert result.unresolved[0].reason == "unsupported-instruction-affects-pcode-store"
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_backend_abstract_values.py -x
```

Expected: import failure.

- [ ] **Step 3: Implement finite values and x86 transfers**

Begin from the accepted Task 4 control-target contexts and provenance. Implement exact join/equality/canonical keys; model registers, flags needed for finite branch refinement, stack slots/arguments, effective addresses, memory widths, calls/returns, and exact globals. Preserve typed origin plus byte offset across moves, LEA, stack spill/reload, and wrappers. Retain imports as terminal control edges; an unknown/import return that reaches an indirect target and every unmodelled possible internal external escape remain blockers.

- [ ] **Step 4: Implement SCC summary fixpoint**

Process SCCs and functions numerically. A summary records argument-to-return/global flow, allocations, typed reads/writes, and helper effects. Reaching a configured cap (`observed >= limit`) for `max_functions`, `max_finite_targets`, `max_finite_values`, `max_states_per_block`, `max_contexts_per_entry`, `max_scc_iterations`, `max_summary_iterations`, or `max_fixpoint_updates` raises a hard analysis error with configured and observed high-water marks. Test equality-at-cap and over-cap. No SCC or summary loop has an implicit or wall-clock termination condition.

- [ ] **Step 5: Run GREEN/static checks and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_abstract_values.py tests/test_retro_x86_cfg.py tests/test_retro_pe.py
cd ../..
python -m ruff check tools/mwcc_retro/backend_abstract_values.py \
  tools/melee-agent/tests/test_retro_backend_abstract_values.py
python -m py_compile tools/mwcc_retro/backend_abstract_values.py
git diff --check
```

Commit: `feat: propagate retail compiler object values`

---

### Task 6: Prove complete lifecycle, unlink, mutation, rewrite, and emission sites

**Files:**
- Modify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_lifetime_audit.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`

**Interfaces:**
- Produces `build_lifetime_site_inventory(image, cfg, values) -> LifetimeSiteInventory`.
- Inventory contains allocations, reuse/free/rewind/release, unlink classifications, typed field writes, mutation/rewrite/emission sites, hook capture facts, provenance paths, unresolved rows, caps/high-water marks, and `proof_ready`.

- [ ] **Step 1: Add RED semantic classification tests**

Synthetic fixtures include six-shape PCode allocators, ObjObject `0x36` allocation/initialization, dynamic and non-adjacent sizes, cache reuse flags, arena rewind/release, unlink-delete, unlink-reinsert, clone, reorder, replace, spill, coalesce, raw payload rewrite, pseudo-op filtering, encoder, buffer write, and alias-ambiguous stores.

```python
def test_unlink_paths_are_classified_by_following_effect(lifetime_fixture):
    inventory = audit_fixture(lifetime_fixture)
    assert inventory.unlink_at(lifetime_fixture.delete_call).classification == "delete"
    assert inventory.unlink_at(lifetime_fixture.move_call).classification == "move-reinsert"


def test_possible_untyped_alias_to_pcode_bytes_blocks_proof(alias_fixture):
    inventory = audit_fixture(alias_fixture)
    assert not inventory.proof_ready
    assert inventory.unresolved[0].kind == "possible-untyped-pcode-write"
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_backend_lifetime_audit.py -x
```

Expected: site inventory API/classifications absent.

- [ ] **Step 3: Implement allocation and generation-boundary proof**

Classify every call to arena `0x00441F20`, `0x00441F60`, `0x00441FA0`, and `0x00441FE0`. Prove or expand the six PCode and 28 ObjObject candidates through allocation-size, initialization, and typed-use provenance. Classify ObjObject cache transitions and arena rewind/release effects.

- [ ] **Step 4: Implement every unlink/write/mutation/rewrite classification**

Require every raw call to `0x0049D010` to have exactly one delete/move-reinsert/replace result. Inventory all typed/possibly aliasing writes to PCode links/opcode/flags/count/arg kind/arg flags/payload/inline bytes. Emit complete create/delete/reorder/clone/replace/spill/coalesce/rewrite provenance.

- [ ] **Step 5: Implement final emission closure**

Prove walker `0x004A2B70`, encoder call at `0x004A2D17`, sole encoder `0x004A3590`, buffer write at `0x004A2D2B`, pseudo-op survival/removal, code range, relocation, and machine operand field derivation. Any alternative encoder/buffer path expands inventory and blocks until classified.

- [ ] **Step 6: Run exact whole-PE audit**

Require all raw/Ghidra-union arena calls and all discovered unlink/field-write/emission sites to be classified, with no relevant unknown or cap hit. Carry forward and reproduce or explain every named Task 4 retained count/pair, then compare the six known PCode allocations, 28 ObjObject candidates, 102 raw/59 body-owned unlink calls, and sole-encoder facts as lower-bound cross-checks and document every delta.

- [ ] **Step 7: Run GREEN/static checks and commit**

Run the exact lifetime/value/CFG/PE command plus the exact-binary integration selected by the test markers:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_abstract_values.py \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_pe.py -x
```

Then run scoped Ruff, py_compile, JSON parsing, and diff check.

Commit: `feat: prove retail pcode lifetime site closure`

---

### Task 7: Prove opcode layouts and generate byte-identical proof/manifest artifacts

**Files:**
- Create: `tools/mwcc_retro/backend_opcode_layout.py`
- Create: `tools/mwcc_retro/backend_lifetime_proof.py`
- Modify: `tools/mwcc_retro/backend_lifetime_audit.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Create: `tools/melee-agent/tests/test_retro_backend_opcode_layout.py`
- Create: `tools/melee-agent/tests/test_retro_backend_lifetime_proof.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_cli.py`
- Create: `tools/mwcc_retro/tables/gc_125n_lifetime_proof.json`
- Create: `tools/mwcc_retro/tables/gc_125n_lifetime_hooks.json`
- Create: `docs/mwcc-retro-gc125n-lifetime-proof.md`

**Interfaces:**
- Produces `analyze_opcode_layouts(image, cfg, values) -> OpcodeLayoutInventory`.
- Produces `generate_lifetime_bundle(inputs, out_dir) -> GeneratedLifetimeBundle`.
- Produces `resolve_lifetime_bundle(out_dir) -> PublishedLifetimeBundle`; all readers use the manifest-verifying `CURRENT` resolver rather than opening generation files directly, and `PublishedLifetimeBundle.canonical_files()` returns the exact ordered name-to-bytes mapping.
- `GeneratedLifetimeBundle` exposes all nine exact outputs and their canonical digests:
  `raw-pe-cfg.v1.jsonl`, `raw-ghidra-crosscheck.v1.json`,
  `backend-lifetime-sites.candidate.v1.json`,
  `opcode-layouts.candidate.v1.json`, `backend-lifetime-audit.v1.json`,
  `gc_125n_lifetime_hooks.candidate.json`,
  `gc_125n_lifetime_proof.candidate.json`, `gc_125n.candidate.json`, and
  `REPORT.md`.

- [ ] **Step 1: Add RED opcode/custom/variadic/domain tests**

Cover exact 468 IDs/mnemonics/format strings, generic role/kind mapping, custom 3/4/12/13/15/16/199 constructors, variadic 1/19/20/39/54, `V` remaining, `Y` fixed eight, GPR/FPR/vector/special/CR, virtual/physical range evidence, mutation-output stage domains, missing/duplicate/reordered/altered rows, and unknown formats.

- [ ] **Step 2: Add RED generator/determinism/adversarial tests**

```python
def test_generation_is_byte_identical(tmp_path, exact_inputs):
    first = generate_lifetime_bundle(exact_inputs, tmp_path / "first")
    second = generate_lifetime_bundle(exact_inputs, tmp_path / "second")
    assert first.canonical_files() == second.canonical_files()
    assert first.proof_sha256 == second.proof_sha256
    assert first.hook_manifest_sha256 == second.hook_manifest_sha256


def test_unresolved_cfg_prevents_proof_file(tmp_path, unresolved_inputs):
    bundle = generate_lifetime_bundle(unresolved_inputs, tmp_path)
    assert bundle.audit_summary["proof_ready"] is False
    assert "gc_125n_lifetime_proof.candidate.json" not in bundle.canonical_files()
```

Add injected-failure/restart tests at every member write/fsync, manifest
write/fsync, immutable-generation rename/fsync, and `CURRENT` replace/fsync.
The resolver must return the complete previous or complete new nine-member
generation, never mixed/partial files; stale, tampered, missing, or orphaned
generations are rejected or ignored.

- [ ] **Step 3: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_opcode_layout.py \
  tests/test_retro_backend_lifetime_proof.py \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_backend_cli.py -x
```

Expected: module/import failures.

- [ ] **Step 4: Implement exact opcode/constructor/domain analysis**

Read the 468×16 metadata table directly. Derive format mapping from constructor CFG. Audit every custom constructor and variadic count source/bound. Derive stage-specific register domains from class initialization, allocator logic, rewrite paths, and emission constraints; never use the ADDI example or global `0..31` as a rule source.

- [ ] **Step 5: Implement canonical bundle publication**

Emit the nine artifacts above as one immutable same-filesystem generation using compact sorted JSON/JSONL. Construction inside its unpublished staging directory is acyclic and ordered: raw CFG; Ghidra cross-check; lifetime sites; opcode layouts; audit summary; canonical hook manifest and its digest; canonical proof containing that manifest digest and its proof digest; candidate table containing the exact proof registry tuple and exact site gate; report last. Validate proof, hook manifest, digest binding, exact site bijection, canonical ordering, and candidate registry/gate before publication. Candidate table uses the production registry/gate shape but remains only in ignored output.

Flush and `fsync` every member, then write and `fsync` a canonical generation manifest binding the exact nine names, sizes, hashes, compiler identity, and schema; `fsync` staging; rename it to an immutable generation name; and `fsync` the generations parent. Atomically replace a flushed/`fsync`ed temporary `CURRENT` pointer containing the generation name and manifest hash, then `fsync` the output root. The resolver validates `CURRENT`, manifest, and all nine members before returning any path or payload. This is the same all-or-none contract introduced for the transitional Task 4 bundle; independently replacing nine top-level files is forbidden.

- [ ] **Step 6: Run generator twice from the exact validated project**

Run the exact Task 4 `ghidra-setup` command, then invoke the branch-local static command twice and compare every canonical file. The only change from the Task 4 command is `-O "$RUN1"` and `-O "$RUN2"` respectively:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
RUN1="$ROOT/build/mwcc_retro/gc125n-proof/run1"
RUN2="$ROOT/build/mwcc_retro/gc125n-proof/run2"
LOG_ROOT="$ROOT/build/diagnostics/task4-repair-exact/final-independent-runs"
mkdir -p "$LOG_ROOT"
for OUT in "$RUN1" "$RUN2"; do
  test ! -e "$OUT" || {
    echo "refusing nonempty initial proof root: $OUT" >&2
    exit 1
  }
  mkdir -p "$OUT"
done
cd "$ROOT/tools/melee-agent"
advance_independent_root() {
  OUT="$1"
  ATTEMPT=0
  TOTAL_COMPLETED=0
  MAX_TOTAL_COMPLETED=$(PYTHONPATH="$ROOT/tools" python - <<'PY'
from mwcc_retro.x86_cfg import AnalysisLimits

print(AnalysisLimits.__dataclass_fields__["max_producer_domain_queries"].default)
PY
)
  MAX_INVOCATIONS=$((MAX_TOTAL_COMPLETED + 1))
  while :; do
    ATTEMPT=$((ATTEMPT + 1))
    test "$ATTEMPT" -le "$MAX_INVOCATIONS" || return 1
    LOG="$LOG_ROOT/$(basename "$OUT")-$ATTEMPT.log"
    set +e
    DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
      python -m src.cli debug retro probe-backend-map \
      "$ROOT/src/melee/mn/mndiagram.c" \
      -f mnDiagram_DrawFighterHeaders \
      --static-only --melee-root "$ROOT" -O "$OUT" >"$LOG" 2>&1
    STATUS=$?
    set -e
    cat "$LOG"
    if test "$STATUS" -eq 0; then
      PYTHONPATH="$ROOT/tools" python - "$OUT" <<'PY'
import sys
from pathlib import Path

from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle

resolve_lifetime_bundle(Path(sys.argv[1]))
PY
      return 0
    fi
    CHECKPOINT_COMPLETED=$(
      python - "$LOG" "$OUT" "$MAX_TOTAL_COMPLETED" <<'PY'
import re
import sys
from pathlib import Path

pattern = re.compile(
    r"producer checkpoint incomplete: completed_this_run=(\d+);"
    r"discovered=(\d+);validated=(\d+);pending=(\d+);checkpoint_dir=(.+)$"
)
matches = []
for line in Path(sys.argv[1]).read_text().splitlines():
    match = pattern.search(line)
    if match is not None:
        matches.append(match.groups())
assert len(matches) == 1, matches
completed, discovered, validated, pending = map(int, matches[0][:4])
checkpoint_dir = Path(matches[0][4])
max_queries = int(sys.argv[3])
assert 0 < completed <= 2048, completed
assert 0 < discovered < max_queries, (discovered, max_queries)
assert 0 <= validated <= discovered, (validated, discovered)
assert 0 <= pending <= discovered, (pending, discovered)
assert validated + pending <= discovered, (validated, pending, discovered)
expected = Path(sys.argv[2]) / ".producer-domain-checkpoints.v1"
assert checkpoint_dir.resolve() == expected.resolve(), (checkpoint_dir, expected)
print(completed)
PY
    ) || return "$STATUS"
    TOTAL_COMPLETED=$((TOTAL_COMPLETED + CHECKPOINT_COMPLETED))
    test "$TOTAL_COMPLETED" -le "$MAX_TOTAL_COMPLETED" || return 1
  done
}
set -e
advance_independent_root "$RUN1" & PID1=$!
advance_independent_root "$RUN2" & PID2=$!
STATUS=0
wait "$PID1" || STATUS=1
wait "$PID2" || STATUS=1
test "$STATUS" -eq 0
PYTHONPATH="$ROOT/tools" python - "$RUN1" "$RUN2" <<'PY'
import hashlib
import sys
from pathlib import Path

from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle

expected = (
    "raw-pe-cfg.v1.jsonl",
    "raw-ghidra-crosscheck.v1.json",
    "backend-lifetime-sites.candidate.v1.json",
    "opcode-layouts.candidate.v1.json",
    "backend-lifetime-audit.v1.json",
    "gc_125n_lifetime_hooks.candidate.json",
    "gc_125n_lifetime_proof.candidate.json",
    "gc_125n.candidate.json",
    "REPORT.md",
)
first = resolve_lifetime_bundle(Path(sys.argv[1])).canonical_files()
second = resolve_lifetime_bundle(Path(sys.argv[2])).canonical_files()
assert tuple(first) == expected
assert tuple(second) == expected
assert first == second
for name, payload in first.items():
    print(name, hashlib.sha256(payload).hexdigest())
PY
```

Each root starts independently empty, but every expected 2,048-query
`ProducerCheckpointIncomplete` refusal resumes that same root in place only
after the wrapper validates its exact counter/directory shape and proves
positive completed work. A zero-progress, malformed, or unexpected nonzero
exit fails immediately. An
invocation that writes exact producer/lifecycle variants exits nonzero through
that exception and must be followed by another invocation on the same root.
Status zero is the silent zero-new pass; the loop immediately validates its
published generation with `resolve_lifetime_bundle` and returns. The cumulative
completed-query and invocation guards are derived from
`AnalysisLimits.max_producer_domain_queries == 2_000_000`, so even a sequence
of one-query progress refusals is finite.
Running the two independent roots concurrently is allowed after code/review
freeze; copying v6 or either run's checkpoints, ledgers, generations, or
`CURRENT` into the other is forbidden.

Any delta or unresolved diagnostic blocks the task. Retain a refused root and
choose a fresh paired suffix only after corruption, a non-checkpoint failure,
or an explicitly abandoned run—not after an expected checkpoint-budget
refusal. Update every later resolver root to the accepted clean pair. Do not
copy the focused `return-path-publication-v6` bundle or one run into the other,
because that does not prove independent regeneration.

- [ ] **Step 7: Track reviewed proof, manifest, and evidence**

Copy only the byte-identical proof and manifest to their tracked table paths. Document exact proof/manifest digests, initialization `0x00401000`, counts/high-water marks, cross-check deltas, constructor/domain evidence, and regeneration commands. Do not edit installed registry/gate.

- [ ] **Step 8: Run GREEN/static checks and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_opcode_layout.py \
  tests/test_retro_backend_lifetime_proof.py \
  tests/test_retro_backend_instrumentation_proof.py \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_abstract_values.py \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_pe.py \
  tests/test_retro_backend_cli.py
```

Then repeat the exact two-run generator/`cmp` commands from Step 6, run scoped Ruff, py_compile, every tracked JSON through `python -m json.tool`, and diff check. Assert installed registry/gate still empty/false.

Commit: `feat: generate exact retail pcode lifetime proof`

---

### Task 8: Load the exact bundle and install lifecycle/generation hooks

**Files:**
- Create: `tools/mwcc_retro/backend_runtime_instrumentation.py`
- Modify: `tools/mwcc_retro/mwcc_retro_debugger.py`
- Modify: `tools/mwcc_retro/backend_map_probe_hook.py`
- Modify: `tools/mwcc_retro/backend_pcode_snapshot_hook.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_runtime.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_object_snapshot.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_map_evidence.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_cli.py`

**Interfaces:**
- Adds `--instrumentation-table PATH` to existing map and PCode probe commands; default remains installed `gc_125n.json`.
- Installed `gc_125n.json` resolves fixed siblings `gc_125n_lifetime_proof.json` and `gc_125n_lifetime_hooks.json`; ignored `gc_125n.candidate.json` resolves `gc_125n_lifetime_proof.candidate.json` and `gc_125n_lifetime_hooks.candidate.json`. Any other table basename is rejected. `RetroContext` carries exact table path, proof, manifest, compiler digest, lifecycle tracker, installed IDs, and hit IDs.
- Produces `load_runtime_bundle(table_path, compiler_path) -> RuntimeBundle`.
- Produces `LifecycleTracker` with `record_allocation`, `record_recycle`, `record_release`, `sequence_at_stop`, and `generation`.

- [ ] **Step 1: Add RED bundle/load/install tests**

Reject wrong executable, proof, manifest digest, registry tuple, sibling absence, altered breakpoint bytes, wrong capture source, missing/duplicate/extra plan, partial installation, nested call-return mismatch, stale sidecar, and installed-default empty registry. Test candidate table positive without modifying installed table.

- [ ] **Step 2: Add RED lifecycle generation tests**

```python
def test_reused_address_increments_generation():
    tracker = LifecycleTracker()
    first = tracker.record_allocation("pcode", 0x700000, "alloc-1")
    tracker.record_release("pcode", 0x700000, "rewind-1")
    second = tracker.record_allocation("pcode", 0x700000, "alloc-1")
    assert (first.allocation_generation, second.allocation_generation) == (1, 2)
    assert [row.lifecycle_sequence for row in tracker.events] == [0, 1, 2]
```

- [ ] **Step 3: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_object_snapshot.py \
  tests/test_retro_backend_map_evidence.py \
  tests/test_retro_backend_cli.py -x
```

Expected: missing runtime module/options/context/lifecycle behavior.

- [ ] **Step 4: Implement exact bundle loading**

Hash the actual compiler, materialize I-JSON, validate proof shape and independent registry tuple, hash/validate manifest, require proof-manifest digest and site semantic bijection, and re-decode every breakpoint/capture source from exact bytes before constructing gdb breakpoints.

- [ ] **Step 5: Implement lifecycle breakpoint stacks and generations**

For call-return plans, push per-invocation pre-state and pair the exact return address/stack identity; capture EAX only for its matching invocation. Record allocation/recycle/rewind/release effects atomically. Bind all object/PCode events to stopped lifecycle sequence and generation. A plan ID is installed only after every phase/source succeeds.

- [ ] **Step 6: Wire shared installer into existing probes**

Map, dedicated PCode, and one-pass hooks use the same bundle/tracker/installed sets. Pass raw `read_bytes` when the proven PCodeArg layout is available. Unpromoted default remains a controlled `unpromoted` status with empty capabilities; supplied candidate table can produce validation evidence through the identical validators.

- [ ] **Step 7: Run GREEN/static checks and commit**

Run the exact Step 3 test command without `-x`, then the exact focused foundation command in Task 1 Step 7. Run scoped Ruff, py_compile, JSON parsing, and diff check.

Commit: `feat: install proof-bound retail lifecycle hooks`

---

### Task 9: Capture every rewrite, mutation, and emission atomically

**Files:**
- Create: `tools/mwcc_retro/backend_live_probe_selection.py`
- Modify: `tools/mwcc_retro/backend_runtime_instrumentation.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Modify: `tools/mwcc_retro/backend_pcode_snapshot_hook.py`
- Modify: `tools/mwcc_retro/backend_map_probe_hook.py`
- Modify: `tools/mwcc_retro/backend_events.py`
- Modify: `tools/mwcc_retro/backend_trace_assembler.py`
- Modify: `tools/mwcc_retro/backend_pcode_lineage.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_runtime.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_pcode_snapshot.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_pcode_lineage.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_trace_assembler.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_map_evidence.py`
- Create: `tools/melee-agent/tests/test_retro_backend_live_probe_selection.py`

**Interfaces:**
- Produces gap-free site-tagged rewrite/mutation/emission raw events from the bound manifest.
- Produces canonical `backend-live-features.v1.json` summaries and `discover_live_probe_candidates(melee_root, limits)`, `summarize_live_probe_features(map_dir, pcode_dir, out_path)`, `select_live_probe_set(preflight_outputs, candidate_table)`, `validate_live_probe_selection(payload, preflight_root, candidate_table)`, and `validate_live_probe_union(selection, live_root, manifest, candidate_table)`. Discovery uses numeric source/symbol order and explicit candidate/compile caps; selection trusts only observed live features, never source heuristics. The selection payload binds the canonical candidate-table SHA-256 and every selected current-preflight feature-summary SHA-256.
- Map/one-pass finalization receives the real proof, manifest, installed IDs, hit IDs, lifecycle events, event cap, drops, truncation, and errors.
- `expected_site_ids == manifest_site_ids == installed_site_ids`; hit policy is validated separately per run and union.

- [ ] **Step 1: Add RED atomic event and semantic-source tests**

Cover before/after raw 12-byte rewrite, changed-kind/flags rejection, nested mutation pairing, incomplete pair, create/delete/reorder/clone/replace/spill/coalesce chronology, duplicate output, parent lineage, stale generation, sequence gap, wrong site family, unexpected hit, emission byte/range/relocation/register mapping, cap/drop/truncation/error, and vector lineage anchor abstention.

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_pcode_snapshot.py \
  tests/test_retro_backend_pcode_lineage.py \
  tests/test_retro_backend_trace_assembler.py \
  tests/test_retro_backend_map_evidence.py \
  tests/test_retro_backend_live_probe_selection.py -x
```

Expected: production has no emit call sites, has no live-feature selector, and still finalizes with empty proof/hooked IDs.

- [ ] **Step 3: Implement rewrite and mutation handlers**

At each manifest phase, independently compute and validate capture sources. Rewrite captures exact before/after PCodeArg and preserves kind/flags unless a bound mutation accounts for other bytes. Mutation events publish only after complete paired input/output snapshots; failures record fatal diagnostics without a partial success event.

- [ ] **Step 4: Implement emission handler**

Bind final PCode/lifecycle identity to encoder input, returned word/buffer write, exact byte ranges, relocations, and decoded machine fields. Reuse the strict existing code-range validator. Unsupported vector machine decoding withholds only the anchor capability while retaining valid vector lineage diagnostics.

- [ ] **Step 5: Remove every proof-capable placeholder path**

Delete production calls that pass `proof=None`, three empty proof inventories, or `hooked_site_ids=set()` when a validated bundle exists. Capabilities are derived only after real proof/manifest/site/event/lineage validation.

- [ ] **Step 6: Add deterministic preflight discovery and observed-feature summaries**

Statically discover a bounded numeric candidate corpus from real matched source functions using source/symbol metadata only as search seeds: small functions with locals; functions with address materialization; and floating-point/high-pressure functions. Publish neither category as proven. For each completed map/PCode probe pair, derive `named_local_identities`, `address_taken_multi_virtual_bindings`, `fpr_allocation_events`, and `spill_events` only from validated live rows. The FPR/spill category requires both nonempty event sets in the same trace. `select_live_probe_set` chooses the first numeric qualifying row per category, rejects feature claims without cited event IDs, and writes exact `why` plus `observed_features` evidence. Candidate discovery, compile attempts, and accepted outputs each have explicit caps that fail when reached.

- [ ] **Step 7: Run GREEN/static checks and commit**

Run the exact Step 2 command without `-x`, then `python -m pytest -o addopts='' tests/test_retro_backend_*.py tests/test_retro_struct_map.py`. Run scoped Ruff, py_compile, JSON parsing, and diff check.

Commit: `feat: capture proof-bound retail pcode events`

---

### Task 10: Run four live probes, promote the exact tuple, and verify the branch

**Files:**
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Modify: `docs/mwcc-retro-gc125n-lifetime-proof.md`
- Modify focused tests only where the exact promoted tuple/site inventories are required.

**Interfaces:**
- Consumes the ignored candidate table and tracked proof/manifest from Task 7.
- Produces one installed promoted tuple, one validated nonempty site gate, four live evidence summaries, and a union-hit validation.

- [ ] **Step 1: Preflight and record the three evidence-driven fixture choices**

Use existing named-local, one-object-to-multiple-virtual, FPR, and spill unit evidence only as search seeds. Run bounded diagnostic probes to select one small named-local function, one address-taken/multi-virtual function, and one function that actually exhibits both FPR allocation and spill in the same live trace. Do not accept `lb_8000CE30` or another historical label without observed facts. Record source, function, why it qualifies, and exact observed features in the ignored deterministic file `build/mwcc_retro/gc125n-proof/live-probe-selection.json`. It must contain exactly four ordered rows with categories `complex-control`, `named-local`, `address-taken-multi-virtual`, and `fpr-and-spill`; the first row is exactly source `src/melee/mn/mndiagram.c`, function `mnDiagram_DrawFighterHeaders`.

Run the audited Task 9 library directly; this extends the existing probes and adds no top-level CLI command:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
PROOF_ROOT="$ROOT/build/mwcc_retro/gc125n-proof"
CANDIDATE=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n.candidate.json"))
PY
)
SEEDS="$PROOF_ROOT/live-probe-preflight-seeds.json"
SELECTION="$PROOF_ROOT/live-probe-selection.json"
LIMITS="$PROOF_ROOT/live-probe-preflight-limits.json"
rm -rf "$PROOF_ROOT/preflight"
rm -f "$SEEDS" "$SELECTION" "$LIMITS"
mkdir -p "$PROOF_ROOT/preflight"
cd "$ROOT"
python - "$ROOT" "$SEEDS" "$LIMITS" <<'PY'
import json, pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import (
    PreflightLimits, discover_live_probe_candidates,
)
limits = PreflightLimits(
    max_candidates=129,
    max_compile_attempts=257,
    max_outputs=129,
)
rows = discover_live_probe_candidates(
    pathlib.Path(sys.argv[1]), limits,
)
pathlib.Path(sys.argv[2]).write_text(
    json.dumps({"schema_version": "mwcc-retro-live-probe-seeds.v1", "candidates": rows},
               sort_keys=True, separators=(",", ":")) + "\n"
)
pathlib.Path(sys.argv[3]).write_text(
    json.dumps(limits.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
)
PY
cd "$ROOT/tools/melee-agent"
MAX_ATTEMPTS=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_compile_attempts"])' "$LIMITS")
MAX_OUTPUTS=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_outputs"])' "$LIMITS")
ATTEMPTS=0
OUTPUTS=0
while IFS=$'\t' read -r ORD SRC FN; do
  OUT="$PROOF_ROOT/preflight/$ORD"
  ATTEMPTS=$((ATTEMPTS + 1))
  test "$ATTEMPTS" -lt "$MAX_ATTEMPTS" || { echo "preflight compile-attempt cap reached" >&2; exit 1; }
  DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
    python -m src.cli debug retro probe-backend-map "$ROOT/$SRC" -f "$FN" \
    --instrumentation-table "$CANDIDATE" --melee-root "$ROOT" -O "$OUT/map"
  ATTEMPTS=$((ATTEMPTS + 1))
  test "$ATTEMPTS" -lt "$MAX_ATTEMPTS" || { echo "preflight compile-attempt cap reached" >&2; exit 1; }
  DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
    python -m src.cli debug retro probe-backend-pcode "$ROOT/$SRC" -f "$FN" \
    --instrumentation-table "$CANDIDATE" --melee-root "$ROOT" -O "$OUT/pcode"
  OUTPUTS=$((OUTPUTS + 1))
  test "$OUTPUTS" -lt "$MAX_OUTPUTS" || { echo "preflight output cap reached" >&2; exit 1; }
  PYTHONPATH="$ROOT" python - "$OUT" "$SRC" "$FN" <<'PY'
import pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import summarize_live_probe_features
out = pathlib.Path(sys.argv[1])
summarize_live_probe_features(out / "map", out / "pcode",
                              out / "backend-live-features.v1.json",
                              source=sys.argv[2], function=sys.argv[3])
PY
  if PYTHONPATH="$ROOT" python - "$PROOF_ROOT/preflight" "$SELECTION" "$CANDIDATE" <<'PY'
import json, pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import (
    IncompleteSelectionError, select_live_probe_set, write_live_probe_selection,
)
paths = sorted(pathlib.Path(sys.argv[1]).glob("*/backend-live-features.v1.json"))
try:
    payload = select_live_probe_set(paths, json.loads(pathlib.Path(sys.argv[3]).read_text()))
except IncompleteSelectionError:
    raise SystemExit(1)
write_live_probe_selection(payload, pathlib.Path(sys.argv[2]))
PY
  then
    break
  fi
done < <(python - "$SEEDS" <<'PY'
import json, pathlib, sys
for index, row in enumerate(json.loads(pathlib.Path(sys.argv[1]).read_text())["candidates"]):
    print(f'{index:04d}\t{row["source"]}\t{row["function"]}')
PY
)
test -f "$SELECTION"
PYTHONPATH="$ROOT" python - "$SELECTION" "$PROOF_ROOT/preflight" "$CANDIDATE" <<'PY'
import json, pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import validate_live_probe_selection
payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
candidate = json.loads(pathlib.Path(sys.argv[3]).read_text())
errors = validate_live_probe_selection(
    payload, melee_root=pathlib.Path("../.."),
    preflight_root=pathlib.Path(sys.argv[2]), candidate_table=candidate,
)
if errors:
    raise SystemExit("; ".join(errors))
PY
```

Reaching any candidate/compile/output cap before a complete selection is a hard failure. `select_live_probe_set` writes exact event IDs and raw facts supporting each `why` and `observed_features` field and proves the FPR and spill events came from the same trace.

- [ ] **Step 2: Run the four bounded candidate-table probes**

Validate the selection file and run both existing probes with the exact ignored candidate table exercised by the two static runs:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
PROOF_ROOT="$ROOT/build/mwcc_retro/gc125n-proof"
CANDIDATE=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n.candidate.json"))
PY
)
SELECTION="$PROOF_ROOT/live-probe-selection.json"
cd "$ROOT/tools/melee-agent"
PYTHONPATH="$ROOT" python - "$SELECTION" "$PROOF_ROOT/preflight" "$CANDIDATE" <<'PY'
import json, pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import validate_live_probe_selection
payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
candidate = json.loads(pathlib.Path(sys.argv[3]).read_text())
errors = validate_live_probe_selection(
    payload, melee_root=pathlib.Path("../.."),
    preflight_root=pathlib.Path(sys.argv[2]), candidate_table=candidate,
)
if errors:
    raise SystemExit("; ".join(errors))
PY
while IFS=$'\t' read -r SRC FN; do
  for PROBE in probe-backend-map probe-backend-pcode; do
    DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
      python -m src.cli debug retro "$PROBE" "$ROOT/$SRC" -f "$FN" \
      --instrumentation-table "$CANDIDATE" --melee-root "$ROOT" \
      -O "$PROOF_ROOT/live/$FN/$PROBE"
  done
done < <(python - "$SELECTION" <<'PY'
import json, pathlib, sys
for row in json.loads(pathlib.Path(sys.argv[1]).read_text())["probes"]:
    print(f'{row["source"]}\t{row["function"]}')
PY
)
```

The four selected rows are:

1. `mnDiagram_DrawFighterHeaders`;
2. the preflight-proven small named-local function;
3. the preflight-proven address-taken/multi-virtual function; and
4. the preflight-proven FPR/spill function.

Each run must validate exact compiler/proof/manifest/digest tuple, exact installed IDs, every `per-run` hit, gap-free lifecycle/PCode sequences, no errors/drops/caps/truncation, correct generations, mutation chronology, virtual-to-physical rewrites, same-run lineage, and exact code bytes/relocations/ranges/machine mappings.

- [ ] **Step 3: Validate four-run union coverage**

Run the closed validator and retain its ignored canonical result:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
PROOF_ROOT="$ROOT/build/mwcc_retro/gc125n-proof"
CANDIDATE=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n.candidate.json"))
PY
)
HOOKS=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n_lifetime_hooks.candidate.json"))
PY
)
SELECTION="$PROOF_ROOT/live-probe-selection.json"
cd "$ROOT"
PYTHONPATH="$ROOT" python - "$SELECTION" "$PROOF_ROOT/live" \
  "$HOOKS" "$CANDIDATE" \
  "$PROOF_ROOT/live-probe-union.json" <<'PY'
import json, pathlib, sys
from tools.mwcc_retro.backend_live_probe_selection import validate_live_probe_union
selection = json.loads(pathlib.Path(sys.argv[1]).read_text())
manifest = json.loads(pathlib.Path(sys.argv[3]).read_text())
candidate = json.loads(pathlib.Path(sys.argv[4]).read_text())
result = validate_live_probe_union(selection, pathlib.Path(sys.argv[2]), manifest, candidate)
if result["errors"]:
    raise SystemExit("; ".join(result["errors"]))
pathlib.Path(sys.argv[5]).write_text(
    json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
)
PY
```

The validator separately requires candidate expected IDs, manifest IDs, and every run's installed IDs to be equal; candidate and live tuple/site-list values to be identical; each run's hit IDs to contain every `per-run` ID; and the union of the four hit sets to equal every manifest ID, with zero exemptions. If any run or union fails, correct the static proof, hook plan, producer, or fixture selection from independent evidence; do not weaken validation or delete a difficult site.

- [ ] **Step 4: Add promotion RED/negative tests**

Before editing `gc_125n.json`, add exact tests expecting one promoted row/gate and verify they fail against the empty installed registry. Add negatives for altered executable digest, proof ID/digest, manifest digest, every site inventory, ordering, empty row, duplicate row, and hostile nested containers.

- [ ] **Step 5: Promote the byte-identical exercised tuple**

Before editing, require byte equality between the candidate proof/manifest used by every live run and the tracked files:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
PROOF_ROOT="$ROOT/build/mwcc_retro/gc125n-proof"
PROOF=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n_lifetime_proof.candidate.json"))
PY
)
HOOKS=$(PYTHONPATH="$ROOT/tools" python - "$PROOF_ROOT/run1" <<'PY'
import sys
from pathlib import Path
from mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
print(resolve_lifetime_bundle(Path(sys.argv[1])).path("gc_125n_lifetime_hooks.candidate.json"))
PY
)
cd "$ROOT"
cmp "$PROOF" \
  "$ROOT/tools/mwcc_retro/tables/gc_125n_lifetime_proof.json"
cmp "$HOOKS" \
  "$ROOT/tools/mwcc_retro/tables/gc_125n_lifetime_hooks.json"
```

Copy exactly one candidate registry row and exact nonempty rewrite/mutation/emission site lists into `gc_125n.json`; set `validated=true`. Do not regenerate or hand-edit a different digest/list. Immediately reload candidate and installed tables through `load_runtime_bundle` against the exact compiler and assert equality of executable digest, proof ID/digest, manifest digest, registry row, expected site IDs, and each rewrite/mutation/emission site list. Re-run the Step 3 validator against the promoted installed table: installed IDs must equal all manifest IDs, each run need hit only every `per-run` ID, and only the four-run union must equal all manifest IDs. Update evidence doc with final commit precursor, proof/manifest digests, static coverage/high-water summary, four per-run hit sets, union set, and probe commands/results.

- [ ] **Step 6: Run focused and adjacent GREEN verification**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' tests/test_retro_backend_*.py tests/test_retro_struct_map.py
```

Then run proof/lineage/object/frame/IG/PCode/runtime/CLI suites explicitly if shell glob ordering omitted any file. Expected: zero failures and pristine output.

- [ ] **Step 7: Run static and full repository verification**

Run scoped Ruff on every changed Python file, py_compile on every changed production Python file, `python -m json.tool` on every changed JSON file, both exact deterministic generator runs with `cmp`, `git diff --check`, and from the worktree root:

```bash
python configure.py && ninja
```

Any suspected pre-existing failure must be reproduced at base `3d3c3fbbc` in a separate read-only/temp checkout and documented; do not ignore it.

- [ ] **Step 8: Commit promotion**

Commit: `feat: promote exact retail pcode lifetime proof`

## Controller completion after Task 10 review

The root controller, not a task implementer, performs these ordered gates:

1. Finish the private-page arena gates in order: local synthetic tests, focused
   exact-root checks for `0x435620` and `0x435a8c`, then its full suite. Do not
   begin a final accepted bundle from a partially reviewed arena change.
2. Retain the companion plan's diagnostic 29/30 split, finish Task 4A's
   independent generic `0x4b1f95` ESP-slot proof, and require zero final
   unresolved control targets with no publication provenance at that address.
3. Run the full parent Task 4 and companion Task 8 verification. Then resume
   `return-path-publication-v6` in place across parsed positive-progress
   checkpoint refusals until the first status-zero pass; fail on zero progress,
   then resolve and verify its accepted bundle.
4. Freeze proof-affecting code and independently advance the initially empty
   `run1` and `run2` roots across every parsed positive-progress checkpoint
   refusal until each returns status zero. Bounded cumulative progress prevents
   an infinite resume loop. That successful invocation is the silent zero-new
   pass. Require byte-equal resolver-validated canonical files.
5. Complete Tasks 8 and 9, run the four exact live probes and union gate from
   resolver-selected `run1`, and only then promote the exercised tuple in Task
   10. Re-run the full Task 10 verification commands fresh.
6. Generate a whole-branch review package from merge-base to HEAD and dispatch
   the most capable independent reviewer. Send the complete Critical/Important
   finding set to one fix subagent, re-run covering tests, and re-review until
   clean. Any proof-affecting fix invalidates the freeze and repeats Gates 3-5.
7. Before any post-freeze merge rehearsal, preserve and fingerprint the main
   checkout's untracked `.coverage` and `docs/superpowers/order-targets/`
   outside the repository. Record
   `git status --short -- .coverage docs/superpowers/order-targets/`, a SHA-256
   of `.coverage` when present, and
   a sorted path/size/SHA-256 manifest of every regular file under
   `order-targets/` as the immutable pre-rehearsal baseline.
8. Repeat `git merge-tree --write-tree --messages master codex/issue-1240-retail-pcode-proof`
   after the final freeze and compare its conflict inventory with the recorded
   20-conflict baseline. Rehearse the resolutions and merged verification in a
   disposable worktree; never merge experimentally in `/Users/mike/code/melee`
   or the issue worktree. Immediately after removing the disposable rehearsal,
   require the main checkout's status and both fingerprints to equal the Gate
   7 baseline; restore from the preservation copy and stop if either differs.
9. Use `superpowers:finishing-a-development-branch`; the user's handoff already
   selects local merge into `master`, so do not pause for an option prompt. In
   `/Users/mike/code/melee`, apply the rehearsed resolutions, merge
   `codex/issue-1240-retail-pcode-proof` into `master`, and verify the merged
   result again. Immediately compare `.coverage` and `order-targets/` status
   and fingerprints with the same pre-rehearsal Gate 7 baseline; restore from
   the preservation copy and stop before issue resolution if either differs.
10. Replay `/opt/homebrew/bin/melee-agent` from main/master, confirming the
    editable install now sees merged tooling.
11. Resolve issue #1240 with final commit, proof and manifest digests, static
    coverage/high-water summary, and all four live probe results.
12. Run `DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof melee-agent issue list`
    and continue any newly opened actionable issue.
