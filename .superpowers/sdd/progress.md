# Issue #1240 Progress Ledger

Foundation-Task3: complete (ea3d1ca65..660606143)
Task 4 repair: committed (00cc81e78, 350b1b116, c5fc95821)
- movzx guard resolves global dispatch table 0x560648
- 99 tables created (217 code entries each, 39 data entries skipped)
- Type-3 relocation adjustment: raw RVA + image_base = loaded VA
- Fixed-point iteration: resolving one table exposes new call sites
- 428 focused tests pass; exact compiler verification is slow (>30 min)

Task 5: complete (8a007cc5f) - value analysis framework
Task 6: complete (3713c941c) - lifetime site inventory
Task 7: complete (e779c6e6a, 1734fb27f) - opcode layouts + proof bundle
Task 8: complete (8fa0bc5e7, 4d4f72b20) - runtime instrumentation + CLI wiring
Task 9: complete (f1c9f832b) - live probe selection

Task 10: partially complete
- 4 live probes verified (lb_8000CE30, lb_8000CDC0, lbArq_80014ABC, gm_801BCC9C)
- Promotion, merge, issue resolution pending

## Branch

codex/issue-1240-retail-pcode-proof: c5fc95821
14 commits above recovery point 7f4e08490
428 focused tests pass, 841 total tests pass, build clean

## Remaining

- Exact compiler verification with full fixed-point dispatch resolution
- Complete value/type analysis to resolve remaining register-based and
  structure-field indirect calls
- Promotion to gc_125n.json, merge, resolve #1240
