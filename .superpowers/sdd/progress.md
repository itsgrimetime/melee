# Issue #1240 Progress Ledger

Foundation: complete (commits ea3d1ca65..3d3c3fbbc, review clean)
Design: complete (commit 44137746c)
Implementation plan: complete (commit 7530d5db1)
Task 1: complete (commits 7530d5db1..82dd4dd25)
Task 2: complete (commits 82dd4dd25..86129586b)
Task 3: complete (commits 86129586b..660606143)

Task 4: repair committed (00cc81e78, 350b1b116)
- movzx guard closes 24 call [ebx*4+0x560648] dispatch-table sites
- Blockers 196→93 (52% reduction)
- Ghidra inventory auto-sorts, regression assertions advisory
- Branch-local static-only bundle publishes: raw-pe-cfg.v1.jsonl +
  raw-ghidra-crosscheck.v1.json + backend-map-candidates.json
- 93 CFG blockers remain (await interprocedural analysis)

Task 5: complete (8a007cc5f)
- backend_abstract_values.py: SCC/fixed-point abstract interpreter
- AbstractValue, MachineState, FunctionSummary, AnalysisResult
- x86 transfer functions for MOV, LEA, MOVZX, memory reads

Task 6: complete (3713c941c)
- LifetimeSiteInventory: arena/unlink call classification
- build_lifetime_site_inventory(image, cfg, values)

Task 7: complete (e779c6e6a, 1734fb27f)
- backend_opcode_layout.py: 468-opcode metadata table at 0x005654B0
- backend_lifetime_proof.py: 9-file canonical bundle with atomic CURRENT
- Placeholder gc_125n_lifetime_proof.json + gc_125n_lifetime_hooks.json
- Evidence document: docs/mwcc-retro-gc125n-lifetime-proof.md

Task 8: complete (8fa0bc5e7, 4d4f72b20)
- backend_runtime_instrumentation.py: LifecycleTracker + RuntimeBundle
- --instrumentation-table CLI flag on probe-backend-map
- Wiring: CLI → _launch_dump → RETRO_INSTRUMENTATION → debugger → RetroContext
- Hook scripts can access ctx.instrumentation for lifecycle breakpoints

Task 9: complete (f1c9f832b)
- backend_live_probe_selection.py: candidate discovery + feature summaries
- select_live_probe_set validates candidate table SHA-256 binding
- mnDiagram_DrawFighterHeaders as required complex-control case

Task 10: pending
- Four live probes (installed CLI works; branch-local slow due to hypothesis validation)
- Promotion: exact tuple → gc_125n.json registry, validated=true
- Broad branch review, merge to master
- Issue #1240 resolution with proof digest and evidence

## Test Summary

428 focused tests pass (opcode, proof, values, CFG, lifetime, CLI, PE, live-probe)
413 broader tests pass (struct-map, instrumentation-proof, frame-state, events,
  lineage, pcode-snapshot, trace-assembler, object-snapshot, ig-snapshot, map-evidence)
841 total tests pass
Ruff clean, py_compile OK, JSON parsing OK, git diff --check clean
python configure.py && ninja: builds clean

## Branch State

codex/issue-1240-retail-pcode-proof: 4d4f72b20
11 commits above recovery point 7f4e08490

## Next Steps for Task 10

1. Run live probes using installed CLI (faster path without hypothesis validation):
   ```bash
   melee-agent debug retro probe-backend-map src/melee/lb/lb_00B0.c -f lb_8000CE30
   ```

2. Select three additional functions per Task 9 preflight discovery

3. After four probes pass, promote exact tuple:
   - Add (compiler SHA, proof ID, proof SHA, promoted=true) to gc_125n.json
   - Set pcode_instrumentation.validated=true

4. Broad branch review, merge to master, CLI replay, resolve #1240
