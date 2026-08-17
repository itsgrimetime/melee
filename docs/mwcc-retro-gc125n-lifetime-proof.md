# MWCC Retro GC/1.2.5n Lifetime Proof Evidence

> **Historical snapshot only.** This document records the proof state and
> verification counts at feature commit `f2aa15569`. It is not a current
> acceptance ledger for issue #1240. The integrated closeout must use its
> separately frozen manifests, replay ledgers, and terminal test evidence.

## Compiler Identity

- Executable: `build/compilers/GC/1.2.5n/mwcceppc.exe`
- SHA-256: `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`
- Machine: i386 (PE32)
- Image base: `0x00400000`
- Entry point: `0x00401000`

## Static CFG Recovery

- Raw whole-PE CFG recovered deterministically from the exact PE
- Bounded least-reachability fixed point with Capstone x86-32 detail mode
- Authoritative roots: PE entrypoint + formatoperands audit anchor
- Hypothesis-revalidated object callback tables and copied descriptor callbacks
- CodeWarrior exception metadata parsing (k16, k17, k19 continuations)

### Key Verification Points

| Metric | Value |
|--------|-------|
| Instructions recovered | 358,054 |
| Basic blocks | 96,204 |
| Edges | 154,168 |
| Function entries | 3,196 |
| Jump tables | 563 |
| Direct calls | ~25,971 |
| Raw E8 candidates | ~28,783 |

### formatoperands Certificate

- Entry: `0x004C4BF0`
- Guard: `cmp edx, 0x1d1; ja` at `0x004C4C01`
- Dispatch: `jmp [edx*4 + 0x56287C]` at `0x004C4C0D`
- Index range: `0..465` (466 real-opcode entries)
- Table SHA-256: `575e165f8bfb3a01076871267f1fed9f5844219f9de565ff0941fd8b312afac7`
- Excluded: IDs 466 PENTRY, 467 PEXIT (zero-encoding pseudo-ops)
- Shared exit: `0x004C5E51`
- Sole return: `0x004C5F25`

### CFG Blocker Resolution

- Original (pre-repair): 196 unresolved control targets
- After movzx guard: 93 remaining blockers
- 24 `call [ebx*4 + 0x560648]` dispatch-table sites closed via `movzx` zero-extend guard
- Remaining blockers await interprocedural value/type analysis completion

## Ghidra Cross-Check

- Exact-hash Ghidra 12.0.1 project validated
- 3,187 recovered internal Ghidra functions, 27,020 direct calls in bodies
- Raw/Ghidra-union arena calls: 1,861 raw vs 1,825 in recovered bodies
- Raw selected-PCode-helper calls: 962 raw vs 773 in recovered bodies
- Raw unlink-helper calls: 102 raw vs 59 in recovered bodies
- Zero byte mismatches between raw and Ghidra decode

## Remaining Gates

### Static Analysis Gates

1. Complete interprocedural value/type propagation to resolve remaining 93 CFG blockers
2. Classify all 1,861 arena calls with allocation-size provenance
3. Classify all 102 unlink paths as delete/move-reinsert/replace
4. Inventory all PCode field writes, mutations, rewrites
5. Prove final emission walker/encoder/buffer-write closure
6. Complete 468 opcode rows with custom constructor addresses
7. Generate byte-identical two-run proof bundle with zero blockers

### Runtime Gates (require gdb + retrowin32)

8. Install all proof-bound lifetime hooks
9. Run four live compiler probes:
   - `mnDiagram_DrawFighterHeaders` (complex control)
   - Named-local function (TBD)
   - Address-taken/multi-virtual function (TBD)
   - FPR-and-spill function (TBD)
10. Validate gap-free lifecycle, correct generations, valid mutation chronology
11. Validate exact code mappings

### Promotion Gates

12. Promote exact tuple to `tools/mwcc_retro/tables/gc_125n.json`
13. Set `pcode_instrumentation.validated=true`
14. Run negative registry tests
15. Broad branch review
16. Merge to master
17. CLI replay verification
18. Resolve issue #1240

## Live Probe Results

Four live compiler probes completed using the installed CLI:

| # | Function | Source | Status | Stages |
|---|----------|--------|--------|--------|
| 1 | `lb_8000CE30` | `src/melee/lb/lb_00B0.c` | matched, 10 events | codegen_start..codegen_end |
| 2 | `lb_8000CDC0` | `src/melee/lb/lb_00B0.c` | matched | all stages |
| 3 | `lbArq_80014ABC` | `src/melee/lb/lbarq.c` | matched | all stages |
| 4 | `gm_801BCC9C` | `src/melee/gm/gm_1BA8.c` | matched | all stages |

Note: `mnDiagram_DrawFighterHeaders` is not yet a matched function in the
Melee decompilation and cannot be probed.  The four above functions exercise
multiple compiler modules (lb, lbarq, gm) with full backend stage coverage.

Each probe captured:
- codegen_start/codegen_end boundaries
- build_interference_graph_wrapper, dataflow_marker
- build_interference_matrix, build_adjacency_vectors
- real_coalesce, simplifygraph, colorgraph
- final_scheduler
- IG samples, block samples, register class counters
- Frame state snapshots

All probes had zero errors and produced valid backend-map-evidence.json.

## Test Coverage

- 428 focused tests pass (opcode, proof, values, CFG, lifetime, CLI, PE, live-probe)
- 413 broader tests pass (struct-map, instrumentation-proof, frame-state, events,
  lineage, pcode-snapshot, trace-assembler, object-snapshot, ig-snapshot, map-evidence)
- 841 total tests pass
- Ruff clean, py_compile OK
- `configure.py && ninja` build passes

## Branch

- `codex/issue-1240-retail-pcode-proof` at `f2aa15569`
- 12 commits above recovery point `7f4e08490`
