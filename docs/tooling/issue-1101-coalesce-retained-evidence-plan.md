# Issue 1101 Coalesce Retained Evidence Plan

## Root Cause

`debug coalesce-search` preserved generated probe source and pcdump evidence only
on successful retained full-TU probes or narrow trace-copy source-shape paths.
When generated probes failed because the compiled pcdump did not contain the
requested target function, failed variants fell back to temp
`melee_coalesce_search_*` source paths and the terminal summary had no durable
pcdump/source evidence.

The follow-up report also used a retained source under `build/diagnostics/...`.
That path is inside the repo but outside `src/`, so treating all in-repo
`--source-file` values as live unit sources skipped the retained full-TU handoff.

## Fix

- Treat `--source-file` paths outside the repo `src/` tree, including
  `build/diagnostics/...`, as retained full-TU inputs.
- Retain generated failed probe sources under
  `build/mwcc_debug_cache/probes/coalesce_search/<function>/...`.
- For `CompileFailure`, expose the attempted pcdump path, compile command,
  stdout, stderr, and return code on failed variants.
- Retain attempted pcdump output if it still exists; otherwise mark
  `pcdump_missing`.
- Aggregate retained sources, pcdump paths, attempted pcdump paths, missing
  counts, and representative compile failures in the terminal summary.

## Regression Coverage

- An inside-repo `build/diagnostics` retained source now uses the full-TU
  retained path and exposes stable failed source/pcdump evidence.
- A generated failure with no pcdump output now reports attempted path and
  compile metadata.
- The existing all-missing-function terminal summary test now asserts durable
  retained source and pcdump evidence.
