# struct verify v2 - auto bases, interior pointers, guarded apply

Date: 2026-06-06
Status: PARTIAL V2 - Codex-reviewed; do not close #439 on this scope alone
Issue: #439

## Problem

The first `struct verify` release proved that `checkdiff` offset discrepancies
can be mapped back to fields, but agents still have to know too much before they
can use it:

- They must pass `--base` or a complete `--base-map`, even when `checkdiff`
  evidence contains only one non-stack base register.
- Interior pointers such as `&info->components[i]` report displacements relative
  to a nested object, so exact top-level offset lookup skips otherwise useful
  discrepancies.
- `--apply` was deferred. Agents need an apply path, but arbitrary header layout
  synthesis is too risky to do silently.

## Goals

1. Make the common command work without `--base` when each function has a unique
   non-stack base register in `classification.offset_discrepancies`.
2. Support interior-pointer bases by normalizing `cur_disp` and `ref_disp` with
   an explicit or inferred base offset before field lookup.
3. Add a conservative `--apply` that edits only when the field change is simple,
   top-level, positive padding before a field, and the post-edit MWCC
   `offsetof` verification passes. Otherwise it must return a concrete
   `not_applicable` reason instead of guessing.

## Non-goals

- Full register dataflow from source or assembly. This v2 only covers rows
  where checkdiff already exposes usable base-register evidence.
- Reordering fields, deleting padding, or editing nested structs automatically.
- Applying multiple conflicting findings in one pass.
- Treating `--apply` as required for normal reporting. Reporting must remain the
  primary safe behavior.

## Design

### Base-register resolution

Per function, explicit inputs still win:

1. `--base-map` entry.
2. `--base`.
3. Auto inference from offset-discrepancy rows.

Auto inference considers only discrepancy rows with a base register outside the
stack and small-data registers (`r1`, `r2`, `r13`). If exactly one base register
appears, use it and report `base_reg_source=unique-offset-discrepancy`. If no
candidate or more than one candidate appears, skip that function with a precise
reason.

This deliberately avoids saying the inferred register is the source struct
pointer. It only means the current diff rows have a single usable base.

### Interior-pointer normalization

The verifier computes `current_abs = base_offset + cur_disp` and
`expected_abs = base_offset + ref_disp` before resolving fields.

Base offset sources:

1. `--base-offset-map` entry for the function.
2. `--base-offset`.
3. Auto inference from the selected discrepancy rows and the known layout.

Auto inference is bounded by the current layout resolver, which enumerates one
level of nested structs, omits pad/unk fields, and samples only early array
indices. It scores every possible offset `field_offset - cur_disp` from that
known layout. A candidate is valid when it maps every selected current
displacement to some known field. If there is exactly one valid candidate, use
it and report `base_offset_source=unique-layout-fit`. If no candidate exists,
use offset zero. If multiple candidates exist, keep offset zero and include an
`interior_offset_candidates` diagnostic so the user can rerun with
`--base-offset`.

Offset zero remains valid and explicit. This keeps existing behavior stable for
ordinary top-level struct pointers.

### JSON output

Each finding should include the current v1 fields plus:

- `base_reg`, `base_reg_source`
- `base_offset`, `base_offset_source`
- `cur_disp`, `ref_disp`
- `current_abs`, `expected_abs`

The top-level JSON should include `skipped` and, when `--apply` is present,
`apply`.

### Guarded apply

`--apply` acts on the aggregated findings already produced by the command.
It may edit only when all of these are true:

- Exactly one non-conflicting finding is selected.
- The field path is top-level, not nested (`.`) and not indexed (`[`).
- `expected_abs > current_abs`.
- The defining header and struct-scoped body span can be found.
- A declaration line for the field inside that struct span can be found
  unambiguously.
- Inserting a `u8 pad_struct_verify_<field>[<delta>];` immediately before that
  field makes `struct_layout.verify_offsets()` pass for the expected offset.

If any guard fails, JSON reports:

```json
{"apply": {"status": "not_applicable", "reason": "..."}}
```

If verification fails after an edit, restore the original file and report
`status=failed`.

This is intentionally narrow. A no-op with a useful reason is better than a bad
header rewrite.

## Relationship to #439

This design is useful partial progress but does not meet the full issue stop
condition. The full #439 asks for minimal assembly/source dataflow and
byte-correct layout proposal/repad/reorder that covers previously warn-skipped
functions. Keep #439 open after landing this v2 unless those broader conditions
are implemented in the same branch.

## Acceptance

- `melee-agent struct verify <function> --struct TYPE --tu-src TU --json` works
  without `--base` for single-base discrepancy rows.
- `--base-offset 0x...` maps interior pointer rows to top-level field paths and
  includes normalized absolute offsets in JSON.
- Ambiguous auto base or ambiguous auto interior offset skips or diagnoses
  instead of fabricating a finding.
- `--apply` is implemented and tested for both a safe struct-scoped top-level
  padding edit and guarded `not_applicable` outcomes.
- Existing v1 explicit `--base` and `--base-map` behavior remains compatible.
