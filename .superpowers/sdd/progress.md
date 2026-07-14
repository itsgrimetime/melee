# Issue #1240 Progress Ledger

Foundation: complete (commits ea3d1ca65..3d3c3fbbc, review clean)
Design: complete (commit 44137746c)
Implementation plan: complete (commit 7530d5db1)
Task 1: complete (commits 7530d5db1..82dd4dd25)
Task 2: complete (commits 82dd4dd25..86129586b)
Task 3: complete (commits 86129586b..660606143)

Task 4: repair committed (00cc81e78)
- movzx guard resolves 24 call [ebx*4+0x560648] dispatch-table sites
- Blockers 196→93 (52% reduction), 358 CFG/lifetime-audit/CLI tests pass

Task 5: complete (8a007cc5f)
- backend_abstract_values.py: SCC/fixed-point abstract interpreter
- 15 focused tests for lattice, transfers, loops, caps, determinism

Task 6: complete (3713c941c)
- LifetimeSiteInventory: arena/unlink classification scaffold
- 22 lifetime audit tests pass

Task 7: complete (e779c6e6a)
- backend_opcode_layout.py: 468-opcode metadata table analysis
- backend_lifetime_proof.py: 9-file canonical bundle with atomic CURRENT
- 17 focused tests for opcodes, constructors, expansions, bundle generation

Task 8: complete (8fa0bc5e7)
- backend_runtime_instrumentation.py: LifecycleTracker + RuntimeBundle
- Gap-free lifecycle sequence, per-(kind,address) generation tracking
- 6 focused lifecycle tests

Task 9: pending
- Requires: live probe selection, rewrite/mutation/emission capture
- Requires: four live compiler runs (gdb + retrowin32 infrastructure)
- Requires: preflight feature discovery from existing map/PCode probes

Task 10: pending
- Requires: promotion of exact tuple to gc_125n.json registry
- Requires: broad branch review, merge to master
- Requires: issue #1240 resolution with proof digest and evidence

## Test summary

424 non-runtime focused tests pass (opcode, proof, values, CFG, lifetime, CLI, PE)
6 runtime lifecycle tests pass
Existing runtime integration tests preserved (may require retrowin32 infrastructure)

## Branch state

codex/issue-1240-retail-pcode-proof: 8fa0bc5e7
7 commits ahead of 7f4e08490 (original recovery point)
