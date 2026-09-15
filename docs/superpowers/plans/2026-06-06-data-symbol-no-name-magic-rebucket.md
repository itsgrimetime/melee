# Data-symbol no-name-magic rebucket plan

Issue: #475.

## Problem

`data-symbol-relocation` harvest rows with
`source_actionability=current-tools-data-symbol` can produce scored
name-magic source candidates but still fail true `--no-name-magic`
validation. Those rows currently record `no_match` with blocker
`no-name-magic-candidate` but no rebucket metadata, so later filtered runs keep
selecting the same exhausted rows.

## Design

- Treat exhausted name-magic candidate evidence as a stable current-tool
  ceiling for the current queue fingerprint.
- Rebucket only name-magic source-declaration results whose blocker is
  `no-name-magic-candidate` and whose source actionability is
  `current-tools-data-symbol`, with at least one scored source-emitting
  candidate that did not report `no_name_magic_match=true`.
- Move those rows to the existing non-runnable
  `blocked-data-symbol-no-name-magic-candidate` actionability.
- Preserve candidate scoring details in the result while adding
  `source_actionability_rebucket` metadata for the existing prior-ledger queue
  overlay.
- Store source and taxonomy-row fingerprints on new rebucket metadata. Prior
  ledger rebuckets with fingerprints apply only when the current source and row
  evidence still match; legacy rebuckets without fingerprints continue to apply
  unconditionally.

## Tests

- Direct name-magic no-match emits rebucket metadata and updates
  `source_actionability`.
- Composed name-magic no-match propagates that metadata to the top-level
  result.
- Prior ledgers containing that rebucket remove matching rows from
  `current-tools-data-symbol` preview and load filters.
- Fingerprint mismatches leave rows selectable for another current-tools run.
- Rows without scored source-emitting no-name-magic exhaustion do not rebucket.
