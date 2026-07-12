# Retail PCode Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and promote an independently auditable `mwcc-retro-lifetime-proof.v1` for the exact retail GC/1.2.5n compiler, then wire complete PCode/ObjObject lifecycle and PCode rewrite/mutation/emission capture into the existing bounded probes.

**Architecture:** First port only the already-reviewed fail-closed proof, object capture, lineage, and diagnostic substrate from the reporter branch. Then derive a deterministic proof JSON from the validated exact-hash Ghidra project and retain the human/auditor-readable evidence beside the generator. Runtime hooks load that exact proof, install every declared site, track allocation generations, and publish capability only when static digest, installed-site coverage, event chronology, and live probes all agree.

**Tech Stack:** Python 3.11, pytest, rfc8785 0.1.4, Capstone 5.x, Ghidra 12 headless analysis, retrowin32/gdb, JSON registry tables.

## Global Constraints

- The compiler executable SHA-256 is exactly `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
- The proof schema is exactly `mwcc-retro-lifetime-proof.v1`, mode `allocation-generation`, basis `exhaustive-static-callgraph-and-disassembly`.
- Do not weaken a validator, invent an address/site/opcode rule, or promote from bounded dynamic survival alone.
- Extend the existing `debug retro probe-backend-map` and `probe-backend-pcode` surfaces; add no new CLI command.
- Do not modify `/Users/mike/.codex/worktrees/b8fa/melee`, merge its full 52-commit stack, or port unrelated causal-differencer/Task 9/Task 10 work.
- Preserve the baseline result: 148 selected tests pass and `test_retro_backend_help_lists_exact_retail_language` is a pre-existing failure.
- Generated compiler binaries, Ghidra databases, and live probe outputs remain ignored artifacts.

---

### Task 1: Curate the reviewed fail-closed substrate

**Files:**
- Create/modify the exact production and test paths touched by commits `938b11e4c`, `66776c45c`, `bb3941411`, `cfade9adb`, `699ac175d`, `40de40ea4`, `c02ae15cf`, `b060989b5`, `dedc367f3`, `fa4f65f57`, `a53bac279`, `b241da8e6`, `f08bc4ef2`, `15ebaf520`.
- Modify: `tools/melee-agent/pyproject.toml`
- Do not add: `.superpowers/sdd/*-report.md`

**Interfaces:**
- Produces `tools/mwcc_retro/backend_instrumentation_proof.py`, object/frame capture, same-run PCode lineage validation, raw PCode event helpers, and fail-closed registry/table gates.
- Preserves current-master CLI behavior and tests outside the port.

- [ ] Cherry-pick each listed commit with `--no-commit`, remove only `.superpowers/sdd/*-report.md` changes from the index/worktree, and commit the four logical groups: proof schema, object/frame capture, PCode lineage, PCode diagnostics.
- [ ] Keep `capstone>=5,<6` from `b060989b5`; add only `rfc8785==0.1.4` from outside the curated stack.
- [ ] Run the focused proof, struct-map, frame, object, IG, lineage, PCode snapshot, runtime, and map-evidence tests with `-o addopts=''`.
- [ ] Run `ruff check`, `python -m py_compile`, `git diff --check`, and confirm `gc_125n.json` still has no promoted proof.
- [ ] Commit and obtain task-scoped spec/code-quality review before Task 2.

### Task 2: Generate an exhaustive exact-compiler proof artifact

**Files:**
- Create: `tools/mwcc_retro/ghidra_scripts/ExportMwccLifetimeProof.java`
- Create: `tools/mwcc_retro/tables/gc_125n_lifetime_proof.json`
- Create: `docs/mwcc-retro-gc125n-lifetime-proof.md`
- Test: `tools/melee-agent/tests/test_retro_backend_instrumentation_proof.py`
- Test: `tools/melee-agent/tests/test_retro_struct_map.py`

**Interfaces:**
- Consumes the validated project produced by `melee-agent debug retro ghidra-setup`.
- Produces a deterministic, canonically ordered proof payload accepted by `validate_instrumentation_proof_payload()` and a written completeness argument covering every unresolved indirect/table path.

- [ ] Add RED tests that reject a wrong executable digest, missing or duplicate lifecycle/rewrite/mutation/emission sites, incomplete 468-opcode inventory, incomplete operand rules, noncanonical ordering, and a changed canonical digest.
- [ ] Export all ObjObject/PCode allocation/free/recycle sites, allocator register rewrites, create/delete/reorder/clone/replace mutations, final emission paths, the 468-row opcode table, and opcode/PCodeArg role+allocatability rules. The exporter must fail when any computed call/jump relevant to these families is unresolved.
- [ ] Store stable site IDs, image VAs, stages, and entity kinds in the schema’s canonical order. Document how the callgraph/disassembly closure proves exhaustiveness, including the `formatoperands` jump table.
- [ ] Run `melee-agent debug retro ghidra-setup`, run the exporter twice, and assert byte-identical JSON and identical RFC 8785 SHA-256.
- [ ] Validate the JSON through production code while leaving `gc_125n.json` unpromoted.
- [ ] Commit and obtain task-scoped spec/code-quality review before Task 3.

### Task 3: Load the proof and wire complete runtime instrumentation

**Files:**
- Modify: `tools/mwcc_retro/backend_instrumentation_proof.py`
- Modify: `tools/mwcc_retro/backend_onepass_trace_hook.py`
- Modify: `tools/mwcc_retro/backend_map_probe_hook.py`
- Modify: `tools/mwcc_retro/backend_pcode_snapshot.py`
- Modify: `tools/mwcc_retro/backend_pcode_lineage.py`
- Modify: `tools/mwcc_retro/struct_map.py`
- Test: `tools/melee-agent/tests/test_retro_backend_instrumentation_proof.py`
- Test: `tools/melee-agent/tests/test_retro_backend_runtime.py`
- Test: `tools/melee-agent/tests/test_retro_backend_pcode_snapshot.py`
- Test: `tools/melee-agent/tests/test_retro_backend_pcode_lineage.py`
- Test: `tools/melee-agent/tests/test_retro_backend_map_evidence.py`

**Interfaces:**
- Consumes the exact audited proof and returns immutable validated site inventories plus proof ID/digest.
- Produces lifecycle generations and site-tagged rewrite/mutation/emission events whose expected site IDs exactly equal the installed hook IDs.

- [ ] Add RED tests for absent/tampered proof files, partial hook installation, duplicate site IDs, missed lifecycle generations, non-atomic mutation pairs, event gaps, wrong compiler digest, and proof/registry tuple mismatch.
- [ ] Load the audited proof only after exact schema, compiler SHA, RFC 8785 digest, and registry tuple validation.
- [ ] Construct lifecycle capture and install every declared allocation/free/recycle breakpoint. Increment allocation generation on reuse and bind every PCode event to the stopped lifecycle sequence.
- [ ] Install every declared rewrite/mutation/emission breakpoint and capture before/after state atomically. Pass the real proof and exact installed site-ID set into map and one-pass finalization; remove the current `proof=None`, empty inventories, and empty `hooked_site_ids` placeholders.
- [ ] Keep capabilities empty for any error, cap/drop/truncation, sequence gap, unexpected event shape, stale output, or expected-vs-hooked mismatch.
- [ ] Run the full focused port suite, static checks, and task-scoped review.

### Task 4: Run four live probes, promote the exact tuple, and integrate

**Files:**
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Modify: `docs/mwcc-retro-gc125n-lifetime-proof.md`
- Modify tests only where the promoted positive tuple needs an exact fixture.

**Interfaces:**
- Consumes Task 3 instrumentation.
- Produces one promoted tuple keyed by exact compiler SHA, proof ID, and proof SHA-256, with nonempty installed site inventories and `pcode_instrumentation.validated=true`.

- [ ] Run `probe-backend-map`/`probe-backend-pcode` for `mnDiagram_DrawFighterHeaders`, one small named-local fixture, one address-taken/multi-virtual fixture, and one FPR/spill fixture.
- [ ] Require all four runs to have gap-free event sequences, no errors/drops/truncation, exact expected==hooked site coverage, valid same-run lineage, and exact candidate range/machine operand mappings.
- [ ] If any live case fails, fix the producer or correct the static proof from independent evidence; never weaken the gate or simply delete the failing site.
- [ ] Promote the single exact tuple and add negative tests for changed executable/proof/site inventories.
- [ ] Run all `test_retro_backend_*`, `test_retro_struct_map.py`, repository configure/build, Ruff, py_compile, JSON parsing, and `git diff --check`; account separately for the recorded pre-existing CLI-help failure.
- [ ] Obtain broad whole-branch review, fix all Critical/Important findings, re-run verification, merge the branch to `master`, replay the installed CLI from main, resolve issue #1240 with commit/evidence, and re-list the queue.
