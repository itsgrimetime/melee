# Directed Multi-Class Proof Mode Design

## Goal

Issue #725 blocks `debug search directed --directed-from-diff` on functions whose
force-phys proof spans both GPR and FPR allocator classes. The existing directed
objective is single-class by design, so the command should run one proof per
class and aggregate the result instead of failing during setup.

## Scope

This change targets the standalone `debug search directed` command. It does not
change allocator internals, force-vector derivation, or `debug search run`.
Single-class explicit proofs and single-class `--directed-from-diff` output
should preserve their existing JSON shape.

Mixed-class proof vectors should:

- parse into `{class_id: {ig_idx: phys}}` groups,
- run the existing directed search once per class group,
- pass the matching `class_id` and per-class proof to each run,
- emit a top-level aggregate payload with `multi_class: true`,
- include `class_ids`, grouped `proof_force_phys`, and canonical
  `proof_force_phys_csv`,
- retain per-class raw results under `classes`, and
- flatten telemetry with an added `class_id` field so downstream classifiers can
  consume all rows without understanding the nested shape.

The aggregate gate should be conservative: any per-class positive gate remains
positive; all `no_smooth_gradient` gates aggregate to `no_smooth_gradient`;
otherwise report `mixed_class_results`.

## Downstream Evidence

The aggregate payload must remain compatible with `debug solve
allocator-ceiling` evidence rules from #726. For a fully drained mixed-class
run, flattened telemetry should carry each class's blocked proof assignments
and byte mismatch outcomes. Accounting should include per-class details plus
aggregate source-drain and budget status.

## Testing

Regression coverage should prove:

- explicit mixed `--directed-force-phys` no longer errors,
- `--directed-from-diff` mixed output no longer errors,
- the command invokes one directed run per class with only that class's proof,
- aggregate telemetry is class-tagged, and
- allocator-ceiling can classify an aggregate mixed-class exhausted payload.

## Stop Condition

#725 is fixed when the original `mnDiagram3_8024714C` repro reaches the real
directed search path and emits a multi-class JSON payload instead of the
single-class setup error.
