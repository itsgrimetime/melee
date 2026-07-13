# Task 3 Direct Decoder Slice Report

## Status

Implemented the bounded direct-recovery slice in
`tools/mwcc_retro/x86_cfg.py`:

- Capstone x86-32 detail-mode decoding with skip-data disabled;
- a canonical numeric heap seeded from immutable inventory records or sorted
  explicit addresses;
- exact instruction-byte ownership with fail-closed unmapped, overlapping, and
  instruction-interior seed/target checks;
- direct call and branch target discovery with exact source-instruction byte
  provenance;
- deterministic instruction, basic-block, edge, call, seed, diagnostic, and
  high-water output;
- block splitting at targets, calls, conditional/unconditional branches,
  returns, and indirect transfers, with call fallthrough preserved;
- unresolved diagnostics for indirect calls/jumps without computed-flow
  resolution; and
- fail-on-reach enforcement for instruction, block, edge, function, and finite
  target caps.

The preserved direct-CFG fixture required one explicitly authorized closed
initializer subset: an already-owned `mov [absolute mapped non-executable],
imm32 executable-VA` seeds its immediate target. This recovers the indirect
`call eax` at `0x40107D` without scanning through the preceding return or
padding.

## RED Evidence

Before production implementation, the bounded decoder selection failed at the
existing explicit boundary:

```text
$ cd tools/melee-agent
$ python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
    -k 'seed_order_cannot_change or direct_cfg_owns_exact or instruction_interior_and_unmapped or relocation_targeting_instruction_interior' -x
collected 39 items / 35 deselected / 4 selected
tests/test_retro_x86_cfg.py F
E   NotImplementedError: direct x86 CFG decoding is not implemented in the seed-inventory slice
1 failed, 35 deselected
```

## GREEN Evidence

The identical direct selection passed after implementation:

```text
tests/test_retro_x86_cfg.py ....
4 passed, 35 deselected in 0.09s
```

The requested direct tests plus already-green limit/anchor tests also passed:

```text
$ cd tools/melee-agent
$ python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
    -k 'structural_default_limits or every_analysis_cap or audit_anchor_requires or seed_order_cannot_change or direct_cfg_owns_exact or instruction_interior_and_unmapped or relocation_targeting_instruction_interior'
tests/test_retro_x86_cfg.py ................................
32 passed, 7 deselected in 0.08s
```

The successful fixture reports high-water values of 19 instructions, 11
blocks, 10 edges, 5 function entries, and 11 finite numeric targets. A focused
equality check reran recovery with each corresponding configured cap set to
that observed value; every run raised `AnalysisLimitError` with equal
configured and observed values.

Static verification before the final commit:

```text
$ python -m ruff check tools/mwcc_retro/x86_cfg.py \
    tools/melee-agent/tests/retro_pe_fixture.py \
    tools/melee-agent/tests/test_retro_x86_cfg.py
All checks passed!

$ python -m py_compile tools/mwcc_retro/x86_cfg.py
# exit 0

$ git diff --check
# exit 0
```

## Intentional Remainder

The next Task 3 slice still owns:

- the register-mediated initializer at `0x401011`, general initializer
  augmentation, and indexed/cross-block rejection policy;
- executable data-island and canonical-padding ownership;
- independent raw-`E8` classification;
- proof-readiness/unexplained-byte decisions; and
- canonical atomic JSONL output.

Accordingly, this slice does not claim proof readiness and intentionally does
not run the seven tests covering those deferred behaviors as GREEN.

## Concerns

- Indirect transfers are recorded only as unresolved diagnostics. No computed
  target is inferred or followed.
- The closed absolute-immediate initializer case is necessary to exercise the
  preserved direct indirect-transfer assertion, but it is deliberately not a
  substitute for the full initializer analysis.
- Recovery caps mutate only ephemeral analysis state before raising; no
  partial `RawCfg` is returned when a cap is reached.
