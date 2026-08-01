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

The skip is fail-closed: any contract, identity, provenance, checksum, or schema change cannot suppress a trial. The focused test exercises two fresh recovery invocations and verifies the second observes a durable hit, starts no trial, and retains the same recovered instructions, edges, and seed inventory. No active exact replay or checkpoint store was touched during this work.

## Round 1 fix

The contract now uses the separately maintained `relocated-rejection-analysis-v1` semantics version and includes accepted hypotheses, rejected identities, and rejected object bases. A hit retains the current clean baseline for subsequent skipped batches. Persisted high-water marks are exact-key/limit validated and replace the returned CFG telemetry so a resumed result has byte-identical canonical JSONL. New ledger-directory creation fsyncs its parent before record publication.

RED: `python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k relocated_rejection_ledger_contract_mutation_replays -q` failed before the contract fix because a checksum-valid hostile semantic-version mutation was not rejected.

GREEN: `python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k 'durably_skipped_on_identical_resume or relocated_rejection_ledger_contract_mutation_replays or relocated_bootstrap_trials_isolate_transfer_groups or rejected_relocated_trial_rebuilds_after_producer_checkpoint' -q` reported 4 passed; `python -m py_compile tools/mwcc_retro/x86_cfg.py`, scoped Ruff, and `git diff --check` passed.

Soundness: a hostile changed contract is bound to a different expected payload and cannot yield a hit; a checksum-valid contract mutation at the original path is rejected as invalid. Accepted and non-relocated paths remain outside the ledger. The broader hostile matrix and multi-batch counting coverage remain follow-up work.

## Round 2 fix

Rejected identities now use explicit recursive structured JSON, never `repr()`, and are sorted by canonical bytes. The exact contract retains accepted state, rejected identities, and rejected object bases. A two-transfer integration replay proves both persisted relocated batches hit/skip after one clean baseline with no trial recovery, while complete canonical JSONL remains equal.

RED/GREEN commands: `python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k relocated_rejection_ledger_skips_two_batches_with_one_baseline -q`; then `python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k 'durably_skipped_on_identical_resume or relocated_rejection_ledger_contract_mutation_replays or relocated_rejection_ledger_skips_two_batches_with_one_baseline' -q`, `python -m py_compile tools/mwcc_retro/x86_cfg.py`, scoped Ruff, and `git diff --check`. GREEN result: 3 passed, 1157 deselected; static checks passed.

Soundness: each subsequent batch key includes the rejected prefix state; reused clean baselines therefore cannot apply a decision under a different candidate-selection state. No exact artifacts were accessed.

## Round 2 hostile matrix

The strict ledger boundary now has parameterized miss tests for compiler SHA, analysis semantics, limits, seeds, accepted state, rejected identities, rejected object bases, batch target, and provenance. Hostile original-path records cover malformed JSON; missing/extra keys; bad hashes; checksum-valid changed contracts/batches; and missing, extra, boolean, negative, and at-limit high-water rows. All are fail-closed (`contains()` returns no hit). The existing copied-descriptor replay integration now explicitly proves it emits no relocated-ledger hit/skip.

RED/GREEN: the new boundary selection was first run with the new assertions, then `python -m pytest -o addopts='' tools/melee-agent/tests/test_retro_x86_cfg.py -k 'hypothesis_replay_reports_outer_progress or changed_contract_input_misses or changed_batch_input_misses or hostile_record_is_invalid or relocated_rejection_ledger_skips_two_batches_with_one_baseline or durably_skipped_on_identical_resume' -q` passed with 23 passed, 1157 deselected. `python -m py_compile tools/mwcc_retro/x86_cfg.py`, scoped Ruff, and `git diff --check` passed.
