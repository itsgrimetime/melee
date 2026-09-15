# Source-family retained handoff and plateau closure

## Context

Issues #974 and #975 came from the post-ceiling baseline-escape path for
`mnDiagram_SortNamesByKOs` and `mnDiagram_DrawCellNumber`.

`baseline-escape --write-probes` retained primary candidates but left nested
`post_ceiling_source_family_discovery.candidates` as hunks only. Consumers then
had to reapply hunks manually, which is unsafe around repeated source lines.
The Sort source-family rerun also reached a fully scored plateau: two
source-family probes preserved IG44 but still failed IG34, yet baseline-escape
returned a bare actionable status with no terminal or continuation summary.

## Requirements

- `--write-probes` must retain nested source-family discovery candidates as
  concrete `.c` files.
- Retained source-family candidate rows must expose `path`, `candidate_path`,
  and `source_retained`.
- Materialization must use the already bounded function-span patch result, not
  downstream global hunk matching.
- Filenames must be stable and bounded.
- Score-source hints must point at retained source paths.
- A fully scored source-family progress plateau must produce a route-closing
  summary instead of bare actionable output.
- The primary `terminal_summary.kind` must remain compatible with retained
  frontier triage (`no-post-ceiling-*-source-family`).

## Design

Source-family probe generation carries `source_text` only when candidate file
retention is requested. The full source is created by replacing the exact
`find_function` span with a patched function body, so file retention does not
depend on replaying diff hunks against repeated lines.

`generate_baseline_escape_candidate_files` writes primary candidates into the
requested output directory and nested source-family candidates into a
`source-family/` subdirectory. It strips `source_text` unless the caller asks for
inline source, then annotates each row with all retained path field names.

The plateau closure is intentionally narrow. It fires only when every expected
source-family candidate id for the function has been scored, at least one
source-family score made partial progress, no source-family score is exact, and
all progress rows are source-family rows. The route-compatible terminal summary
keeps the existing baseline-escape kind, while the detailed plateau evidence is
stored under `post_ceiling_source_family_plateau_summary` and embedded in
`terminal_summary.source_family_progress_plateau`.

## Review Notes

An independent Codex subagent reviewed the design before implementation. The
main adjustments from review were:

- keep `terminal_summary.kind` compatible with retained-frontier triage;
- require all progress rows to be source-family rows before terminalizing;
- include all three path fields (`path`, `candidate_path`, `source_retained`);
- preserve default compact JSON by only retaining nested full source when
  `--write-probes`/candidate-file generation is used.
