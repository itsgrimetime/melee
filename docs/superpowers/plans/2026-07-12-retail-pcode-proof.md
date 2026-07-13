# Retail PCode Whole-PE Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce, live-validate, promote, and merge one independently auditable retail GC/1.2.5n ObjObject/PCode lifetime proof driven by a deterministic bounded raw whole-PE analysis.

**Architecture:** A strict PE32/x86 parser feeds a deterministic raw CFG and computed-flow recovery layer. A separate interprocedural abstract interpreter classifies lifecycle, field mutation, rewrite, and emission sites; opcode analysis produces all 468 constructor/layout rules; a canonical proof digest binds a canonical runtime-hook manifest. Existing map and PCode probes install that exact manifest, capture gap-free lifecycle and PCode events, and grant capability only after exact static, hook, lineage, code-mapping, and four-probe gates agree.

**Tech Stack:** Python 3.11, Capstone 5.x, RFC 8785 0.1.4, pytest, Ghidra 12 headless cross-checks, retrowin32/gdb, JSON/JSONL, Ruff, Ninja.

## Global Constraints

- The compiler executable SHA-256 is exactly `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
- The proof schema remains the unmerged `mwcc-retro-lifetime-proof.v1`, amended in place; mode is exactly `allocation-generation`; basis is exactly `exhaustive-static-callgraph-and-disassembly`.
- The proof ID is exactly `gc-1.2.5n-backend-entity-allocation-trace.v1`.
- Do not weaken a validator, invent an address/site/opcode/register range/constructor semantic, or substitute bounded dynamic survival for exhaustive static proof.
- Every relevant unresolved control-flow, value-flow, constructor, site, capture-semantic, or emission path fails closed.
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

## Completed reviewed foundation

Commits `1b057f747..3d3c3fbbc` already provide the proof/registry trust substrate, object/frame capture, same-run PCode lineage, fail-closed PCode diagnostics, and independent registry binding. The clean handoff baseline is freshly verified at 439 focused tests. Do not re-dispatch or rewrite this foundation; migrate it through the tasks below.

The approved design is `docs/superpowers/specs/2026-07-12-mwcc-retro-whole-pe-proof-design.md` at commit `44137746c`.

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
- `SeedInventory` records every entrypoint/export, relocation-proven executable pointer, audit anchor, executable function-pointer initializer, and its byte provenance; direct call/branch targets discovered while decoding are added to the same numeric worklist. Task 4 extends it with recovered callback-table targets.
- `RawCfg` contains the canonical seed inventory, instructions, blocks, edges, direct calls, raw E8 candidates, data regions, ownership diagnostics, caps, and high-water marks.

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

Synthetic `.text` includes an entry, export, direct call, fallthrough, conditional branch, return, padding, relocation-proven executable pointer, function-pointer initializer, audit anchor, pointer-referenced data island, and embedded fake `E8` bytes. Test every production seed category and byte provenance, canonical output under reversed seed order, instruction-interior conflicts, unmapped targets, unexplained executable bytes, and equality-at-cap plus over-cap for every cap. A malformed/unmapped/interior seed and an executable relocation or initializer that cannot be classified are unresolved blockers.

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

- [ ] **Step 3: Implement the production seed universe and direct CFG recovery**

Build the initial numeric seed set from the PE entrypoint and every export; every executable target proven by a parsed relocation; every executable pointer in a statically decoded function-pointer initializer; and the closed audited anchors recorded by the design/evidence (`formatoperands`, arena helpers, unlink helper, allocation candidates, mutation/rewrite helpers, final walker/encoder/buffer-write sites). Validate each audit anchor against exact instruction bytes before trusting it and publish its provenance; an anchor is a completeness seed, never semantic proof. Decode Capstone x86-32 with detail mode and skip-data disabled. Add every exact direct call/branch target to the numeric heap worklist. Split blocks on targets, calls, conditional/unconditional branches, returns, and indirect transfers. Maintain exact byte ownership and reject overlap/interior targets. Scan raw executable bytes independently for valid `E8 rel32` targets; require each candidate to be owned instruction or proven data/padding. Any executable relocation/initializer/anchor that is unmapped, interior, ambiguous, or unexplained blocks proof.

- [ ] **Step 4: Implement canonical serialization and atomic JSONL output**

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
- Produces `compare_ghidra_inventory(cfg, inventory) -> CrosscheckReport`.
- `probe-backend-map --static-only` writes raw CFG and cross-check artifacts after the existing exact-hash `ghidra-setup` prerequisite.

- [ ] **Step 1: Add RED computed-flow and cross-check tests**

Cover absolute and base+index tables, bounded callback sets, missing guard, conflicting width/base, unmapped entry, target outside `.text`, 468-way synthetic dispatch, and a Ghidra inventory missing a raw-owned body.

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

- [ ] **Step 2: Run RED**

Run:

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_cli.py -x
```

Expected: failures for missing jump-table/cross-check/static output behavior.

- [ ] **Step 3: Implement finite indirect recovery**

Derive table bounds only from dominating guards or finite abstract target initializers. Record every entry and refuse an unbounded scan. Resolve every recovered callback table through the same algorithm, add every finite executable callback target to `SeedInventory` with table-entry provenance, and iterate raw recovery until no seed/edge/ownership fact changes. Any relevant indirect with no finite target set, any callback entry without finite provenance, or any newly discovered executable initializer outside the closed seed inventory remains an explicit blocker.

- [ ] **Step 4: Export and compare Ghidra evidence**

The Java script emits every recovered Ghidra instruction, function entry/body range, call, computed transfer, data reference, and function-pointer reference in numeric order. It asserts the exact program hash. The Python cross-check reports raw-only, Ghidra-only, byte mismatch, flow mismatch, and ownership mismatch rows without deleting raw facts.

- [ ] **Step 5: Integrate `probe-backend-map --static-only`**

Keep the same command. At this task boundary, extend help/output to write transitional `raw-pe-cfg.v1.jsonl`, `raw-ghidra-crosscheck.v1.json`, and existing `backend-map-candidates.json`. Task 7 replaces this transitional publication with the closed nine-file bundle. The command must execute in this order: load and exact-hash the PE, recover the bounded raw CFG, invoke the validated Ghidra exporter against the already prepared exact-hash project, parse its numeric inventory, and compare it with the raw CFG. A Ghidra mismatch that indicates a raw decode conflict fails; a missing Ghidra owner with consistent bytes/flow is reported.

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

`probe-backend-map --static-only` invokes `tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java` through the validated project and writes its numeric inventory only inside a newly created `tempfile.TemporaryDirectory` outside the output directory. It consumes that exact temporary file before publishing `raw-ghidra-crosscheck.v1.json`, which records the canonical inventory digest, and deletes the temporary directory on both success and failure. It refuses a stale, missing, differently hashed, or manually substituted inventory. The transient exporter inventory is never a published artifact; after Task 7, the fresh published audit directory contains exactly the nine declared bundle artifacts.

- [ ] **Step 6: Run the exact compiler regression**

Require raw recovery to derive `formatoperands` at `0x004C4BF0`, its unsigned bound `0..465`, table base `0x0056287C`, all 466 relocation-backed executable targets, and its exit closure. Assert the exact 466-entry byte digest `575e165f8bfb3a01076871267f1fed9f5844219f9de565ff0941fd8b312afac7` and reject the following unrelocated non-code dwords `0x2d` and `0x4228` as targets. Keep the independent 468-way synthetic dispatch test as a generic boundary case. The separate opcode metadata proof still covers IDs `0..467`; IDs 466 `PENTRY` and 467 `PEXIT` are zero-encoding pseudo-ops whose final-list survival/elimination remains a Task 7 obligation. Reproduce or explicitly explain each retained lower-bound pair as a separately named audit assertion: 3,187 recovered internal Ghidra functions and 27,020 direct calls in their bodies; 1,861 raw/Ghidra-union arena calls versus 1,825 within recovered bodies; 962 raw selected-PCode-helper calls versus 773 within recovered bodies; and 102 raw unlink-helper calls versus 59 within recovered bodies. These are regression cross-checks, never analyzer completeness truth.

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

### Task 5: Add bounded interprocedural values, types, and call summaries

**Files:**
- Create: `tools/mwcc_retro/backend_abstract_values.py`
- Create: `tools/melee-agent/tests/test_retro_backend_abstract_values.py`
- Modify: `tools/melee-agent/tests/retro_pe_fixture.py`

**Interfaces:**
- Produces frozen `AbstractValue`, `MachineState`, `FunctionSummary`, and `AnalysisResult`.
- Produces `analyze_values(image, cfg, roots, limits) -> AnalysisResult`.
- Unknown values retain exact origin/reason and cannot silently enter proof-relevant outputs.

- [ ] **Step 1: Add RED lattice/transfer/fixpoint tests**

Cover exact/finite/affine/null/image/typed pointers, stack arguments, cdecl returns, wrapper calls, globals, loops/SCC convergence, unsupported instructions on relevant versus irrelevant slices, finite-set/state/update cap failures, and deterministic summary ordering.

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

Implement exact join/equality/canonical keys; model registers, flags needed for finite branch refinement, stack slots/arguments, effective addresses, memory widths, calls/returns, and exact globals. Preserve typed origin plus byte offset across moves, LEA, stack spill/reload, and wrappers.

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
    assert not (tmp_path / "gc_125n_lifetime_proof.candidate.json").exists()
```

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

Emit the nine artifacts above using compact sorted JSON/JSONL and atomic temp/fsync/replace. Construction is acyclic and ordered: raw CFG; Ghidra cross-check; lifetime sites; opcode layouts; audit summary; canonical hook manifest and its digest; canonical proof containing that manifest digest and its proof digest; candidate table containing the exact proof registry tuple and exact site gate; report last. Validate proof, manifest, digest binding, exact site bijection, canonical ordering, and candidate registry/gate before publication. Candidate table uses the production registry/gate shape but remains only in ignored output.

- [ ] **Step 6: Run generator twice from the exact validated project**

Run the exact Task 4 `ghidra-setup` command, then invoke the branch-local static command twice and compare every canonical file. The only change from the Task 4 command is `-O "$RUN1"` and `-O "$RUN2"` respectively:

```bash
ROOT=/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof
RUN1="$ROOT/build/mwcc_retro/gc125n-proof/run1"
RUN2="$ROOT/build/mwcc_retro/gc125n-proof/run2"
cd "$ROOT/tools/melee-agent"
for OUT in "$RUN1" "$RUN2"; do
  rm -rf "$OUT"
  mkdir -p "$OUT"
  DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof \
    python -m src.cli debug retro probe-backend-map \
    "$ROOT/src/melee/mn/mndiagram.c" \
    -f mnDiagram_DrawFighterHeaders \
    --static-only --melee-root "$ROOT" -O "$OUT"
done
EXPECTED=$(printf '%s\n' \
  REPORT.md backend-lifetime-audit.v1.json \
  backend-lifetime-sites.candidate.v1.json gc_125n.candidate.json \
  gc_125n_lifetime_hooks.candidate.json \
  gc_125n_lifetime_proof.candidate.json opcode-layouts.candidate.v1.json \
  raw-ghidra-crosscheck.v1.json raw-pe-cfg.v1.jsonl | sort)
for OUT in "$RUN1" "$RUN2"; do
  ACTUAL=$(find "$OUT" -maxdepth 1 -type f -exec basename {} \; | sort)
  test "$ACTUAL" = "$EXPECTED"
done
for NAME in \
  raw-pe-cfg.v1.jsonl raw-ghidra-crosscheck.v1.json \
  backend-lifetime-sites.candidate.v1.json \
  opcode-layouts.candidate.v1.json backend-lifetime-audit.v1.json \
  gc_125n_lifetime_hooks.candidate.json \
  gc_125n_lifetime_proof.candidate.json gc_125n.candidate.json REPORT.md; do
  cmp "$RUN1/$NAME" "$RUN2/$NAME"
  shasum -a 256 "$RUN1/$NAME" "$RUN2/$NAME"
done
```

Any delta or unresolved diagnostic blocks the task.

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
CANDIDATE="$PROOF_ROOT/run1/gc_125n.candidate.json"
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
CANDIDATE="$PROOF_ROOT/run1/gc_125n.candidate.json"
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
CANDIDATE="$PROOF_ROOT/run1/gc_125n.candidate.json"
SELECTION="$PROOF_ROOT/live-probe-selection.json"
cd "$ROOT"
PYTHONPATH="$ROOT" python - "$SELECTION" "$PROOF_ROOT/live" \
  "$PROOF_ROOT/run1/gc_125n_lifetime_hooks.candidate.json" "$CANDIDATE" \
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
cd "$ROOT"
cmp "$PROOF_ROOT/run1/gc_125n_lifetime_proof.candidate.json" \
  "$ROOT/tools/mwcc_retro/tables/gc_125n_lifetime_proof.json"
cmp "$PROOF_ROOT/run1/gc_125n_lifetime_hooks.candidate.json" \
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

1. Generate a whole-branch review package from merge-base to HEAD and dispatch the most capable independent reviewer.
2. Send the complete Critical/Important finding set to one fix subagent, re-run covering tests, and re-review until clean.
3. Re-run the full Task 10 verification commands fresh.
4. Use `superpowers:finishing-a-development-branch`; the user's handoff already selects local merge into `master`, so do not pause for an option prompt.
5. In `/Users/mike/code/melee`, preserve `.coverage` and `docs/superpowers/order-targets/`, merge `codex/issue-1240-retail-pcode-proof` into `master`, and verify the merged result again.
6. Replay `/opt/homebrew/bin/melee-agent` from main/master, confirming the editable install now sees merged tooling.
7. Resolve issue #1240 with final commit, proof and manifest digests, static coverage/high-water summary, and all four live probe results.
8. Run `DECOMP_AGENT_ID=codex-issue-1240-retail-pcode-proof melee-agent issues list` and continue any newly opened actionable issue.
