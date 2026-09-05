# Node-Set-Split Retained Source Design

Date: 2026-06-19
Issues: #851, #852

## Context

`debug solve node-set-split` now consumes staged source candidates retained from
earlier solver campaigns. Two reports expose one workflow gap in that path:

- A retained source file under `build/diagnostics/` is a valid mutation
  baseline, but it is not a build unit. Passing it as both the source text and
  the compile unit makes the same-TU compiler look for a non-existent
  `build/GALE01/build/diagnostics/...o` block.
- Long candidate IDs can exceed filesystem filename limits when the CLI writes
  temporary or retained candidate source files. The write occurs before the
  per-candidate error handler, so the command can crash and emit an empty JSON
  file.

## Goals

- Let `--source-file` point at a retained full source candidate while compiling
  and scoring through the real `src/<unit>.c` build edge.
- Use the retained source text as the baseline for generation, baseline
  allocator signature, and baseline match-percent delta.
- Bound temporary and retained candidate filenames while preserving enough of
  the candidate ID for debugging and adding a stable digest for uniqueness.
- Keep failure handling JSON-producing whenever a single candidate cannot be
  written, retained, compiled, or scored.

## Non-Goals

- Teaching Ninja to build arbitrary `build/diagnostics/*.c` source files.
- Changing the source patch generators or allocator objective semantics.
- Applying retained-source results to the retained file. `--apply-best` should
  still patch the real unit source after a candidate is verified.

## Design

### Retained Source Baseline

Resolve two paths in the CLI:

- `resolved_source`: the user-selected mutation baseline. This may be
  `src/<unit>.c` or an external retained source file.
- `compile_unit_source`: the real source file discovered from
  `build/GALE01/report.json`, always `DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"`.

Candidate generation reads `resolved_source`. Baseline signature and candidate
signature compilation pass `resolved_source` or the temporary candidate path as
the source to transfer, but always pass `compile_unit_source` as
`unit_source`. The existing `_node_set_split_same_tu_compile_path` helper then
temporarily transfers the target function into the real unit, compiles the real
object, restores the source, and preserves pcdump freshness.

Baseline match-percent refresh and realized-candidate scoring follow the same
distinction. If the selected source is the real unit source, keep the existing
direct refresh and function-transfer scoring. If the selected source is
retained, score both the retained baseline and each realized patched candidate
with `_score_source_candidate_real_tree(..., full_unit_source=True)` so unit
level staged edits outside the target function are preserved during the
temporary build. `--apply-best` still writes to the real unit source, using the
same full-unit mode when the selected baseline is retained.

The same-TU helper should transfer whenever `source_path != unit_path`, even if
an external retained copy happens to live in the same directory as the real
unit. Only the exact real unit path can be compiled in place without transfer.

### Bounded Candidate Filenames

`_safe_filename` should sanitize candidate IDs and cap the resulting stem well
below common `NAME_MAX` limits. When truncation is required, append a short
SHA-1 digest of the original ID. Retained source filenames append the source
digest after the bounded stem, so the final basename including
`-{source_digest}.c` must remain under 255 bytes.

Candidate temporary writes should be inside the candidate error handling block,
with diagnostics retention skipped when no candidate file was created.

## Validation

- Regression test: retained `--source-file` generation uses retained text, but
  baseline and candidate compilation receive the real unit source as
  `unit_source`.
- Regression test: retained-source baseline match percent is taken from scoring
  the retained file, so candidate deltas are relative to the staged source.
- Regression test: realized retained-source candidate scoring uses full-unit
  retained patched text, preserving source outside the target function.
- Regression test: very long candidate IDs produce bounded filenames and the
  CLI returns JSON instead of raising `OSError: File name too long`.
- Focused CLI smoke checks for `debug solve node-set-split --help` and
  `debug solve node-set-split` on retained-source fixtures with compiler calls
  monkeypatched by tests.
