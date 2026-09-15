# mnitemsw retained evidence

See [the case study](../../mnitemsw-matching-notes.md) for interpretation.
Final source: PR #3359, commit `69a0d3ee58409a99d5196fcf6e5df3c23342303f`.

- `frontiers.json`: chronological candidate scores and hashes of their full TU
  sources and normal checkdiff results. Intermediate scores are not independent
  one-variable comparisons against the original baseline.
- `working-checkdiff.json`, `pr-checkdiff.json`: final ordinary exact function
  comparisons, each 100%, in the two separate checkouts.
- `working-linked-build.txt`, `pr-linked-build.txt`: full builds passing the
  original DOL checksum with the TU set to Matching.
- `duplicate-data-link-error.txt`: initial linked-address failure despite the
  100% object report; the duplicate table moved the following TU by 32 bytes.
- `before-sbss-fix-elf-info.txt`: intermediate symbol offsets showing the two
  small-BSS objects reversed. Trailing whitespace is trimmed in this copy; the
  archive preserves the raw output. This is not a final-layout artifact.

The larger local evidence archive is independent of worktree and `/tmp` cleanup:

```text
~/.config/decomp-me/matching-evidence/mnitemsw-2026-09-06/
  diagnostics.tar.gz
  manifest.json
  notes/
```

The archive contains 535 text artifacts (33,597,723 uncompressed bytes), including
candidate source, checkdiff output, sweep scripts, pcdumps, retail allocator-cost
snapshots, compiler analysis, and earlier checkpoints. No compiler/game binaries
are included. Every archived file was read back and checked against its SHA-256
in `manifest.json` after creation. Archive SHA-256:

`7fa0534ef932c05b36f51fec78c647a04377f8d9665f9d97796d29b270e8c85b`

Archive member names preserve the old `c016-*` names without the `/tmp/` prefix.
Extract into a new directory, not over a working source tree. Diagnostic scripts
record original paths and may need path changes before rerunning; snapshots are
readable without running those scripts.
