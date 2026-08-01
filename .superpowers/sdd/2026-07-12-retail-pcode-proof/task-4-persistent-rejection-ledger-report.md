# Task 4 persistent relocated-rejection ledger

## Design

`_RelocatedRejectionLedger` stores one atomic JSON record per fully rejected relocated-dispatch batch below the producer checkpoint directory. Its lookup key binds compiler image SHA-256, ledger analysis schema, complete limits, authoritative initial seed inventory, canonical accepted-hypothesis state, and the complete canonical relocated batch including seed provenance. Records also contain a SHA-256 over their complete unsigned payload. A missing, malformed, tampered, or mismatched record is a miss and forces normal recovery.

Only a relocated batch with zero reproduced selected hypotheses publishes a record. Object and copied-descriptor hypotheses never consult the ledger, and accepted hypotheses continue normal replay/revalidation. Writes use a same-directory temporary file, file fsync, atomic replace, and directory fsync. Progress callbacks report miss, invalid, hit, write, and skip events.

## TDD evidence

RED:

`python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k durably_skipped_on_identical_resume -q`

Result: failed because the expected `rejection-ledger-write` telemetry did not exist.

GREEN:

`python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k 'durably_skipped_on_identical_resume or relocated_bootstrap_trials_isolate_transfer_groups or rejected_relocated_trial_rebuilds_after_producer_checkpoint' -q`

`python -m py_compile tools/mwcc_retro/x86_cfg.py`

`python -m ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py`

`git diff --check`

Result: 3 passed, 1155 deselected; static checks passed.

## Files changed

- `tools/mwcc_retro/x86_cfg.py`
- `tools/melee-agent/tests/test_retro_x86_cfg.py`
- this report

## Soundness and concerns

The skip is fail-closed: any contract, identity, provenance, checksum, or schema change cannot suppress a trial. The focused test exercises two fresh recovery invocations and verifies the second observes a durable hit, starts no trial, and retains the same recovered instructions, edges, and seed inventory. Canonical JSONL high-water telemetry differs between forced-trial and skipped replay because it records transient analysis work; the semantic CFG outcome is unchanged. No active exact replay or checkpoint store was touched during this work.
