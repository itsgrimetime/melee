# Task 3 Seed Inventory Slice Report

## Status

Implemented the bounded, decoder-free Task 3 foundation:

- immutable public analysis-limit, audit-anchor, seed-inventory, and raw-CFG
  record shapes;
- structural default limits derived from executable section raw bytes;
- fail-closed equality/over-cap checks with configured and observed high-water
  values;
- canonical initial seed discovery for the PE entry point, every direct export,
  relocation-proven executable dword targets, and exact audited anchors; and
- explicit `NotImplementedError` boundaries for direct x86 decoding and atomic
  JSONL output.

## RED / GREEN Evidence

RED before production implementation:

```text
$ cd tools/melee-agent
$ python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
    -k 'test_structural_default_limits or test_every_analysis_cap or test_seed_inventory or test_audit_anchor' -x
collected 0 items / 1 error
E   ModuleNotFoundError: No module named 'tools.mwcc_retro.x86_cfg'
```

The controller then narrowed this slice's accepted GREEN selection because the
existing `test_seed_inventory_records_every_production_category_and_bytes`
intentionally exercises `recover_cfg` and decoder-owned initializer/direct-flow
records:

```text
$ cd tools/melee-agent
$ python -m pytest -o addopts='' tests/test_retro_x86_cfg.py \
    -k 'structural_default_limits or every_analysis_cap or audit_anchor_requires'
collected 39 items / 11 deselected / 28 selected
tests/test_retro_x86_cfg.py ............................ [100%]
28 passed, 11 deselected in 0.08s
```

The synthetic inventory was also inspected directly. Its canonical initial
records were entry point `0x401000`, export `0x401040`, relocation-proven target
`0x401060` from slot `0x402080` with bytes `60104000`, and audited anchor
`0x401070`.

## Static Evidence

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

## Files

- `tools/mwcc_retro/x86_cfg.py` — new immutable records, analysis limits,
  audit-anchor validation, initial seed inventory, and unfinished decoder
  boundaries.
- `tools/melee-agent/tests/retro_pe_fixture.py` — preserved prior RED synthetic
  PE/CFG fixture work.
- `tools/melee-agent/tests/test_retro_x86_cfg.py` — preserved prior RED Task 3
  tests, including intentional decoder-slice failures.
- `.superpowers/sdd/task-3-seed-report.md` — this handoff report.

## Intentional Remaining Decoder Work

The next Task 3 slice must implement `recover_cfg` and `write_jsonl_atomic`.
That work owns Capstone decoding, instruction/block/edge ownership, interior
target rejection, intrablock function-pointer initializer evidence, direct
call/branch target augmentation, data/padding/E8 classification, canonical
serialization, and recovery-time unresolved diagnostics. The remaining CFG
tests were intentionally not run as GREEN and are not represented as proof
ready.

## Self-review and Concerns

- No decoder behavior is hidden in seed discovery. Relocation processing only
  reads wholly mapped four-byte non-executable slots and records values that
  lie in declared executable ranges; instruction-boundary validation remains a
  recovery responsibility.
- Audit anchors bind non-empty exact bytes, address, evidence, and SHA-256.
  Inventory construction independently re-reads the mapped executable bytes
  and rejects a byte or digest mismatch.
- Entry/export byte provenance currently binds the first executable byte at the
  seed address. Relocation and audit-anchor provenance retain their full exact
  evidence bytes. If the decoder slice adopts a longer first-instruction byte
  span, it should update entry/export records only with matching tests.
- The public raw-CFG record shapes are immutable scaffolding. Their semantic
  population and any additional decoder-specific fields remain intentionally
  open for the next slice.
