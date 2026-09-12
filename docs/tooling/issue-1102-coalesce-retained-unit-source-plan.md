# Issue 1102 Coalesce Retained Unit Source Plan

## Root Cause

`debug coalesce-search` used `source_path_for_probes` for two different roles:
the source text seed used to generate probes, and the buildable same-TU source
used as `--unit-source` for full-TU retained compiles.

After issue 1101, repo-local retained sources under `build/diagnostics/...` were
correctly classified as retained full-TU inputs. However, the same diagnostics
path was also passed as `--unit-source`, so `debug dump local` looked for a
Ninja build edge under `build/GALE01/build/diagnostics/...` and every generated
probe failed before scoring.

## Fix

- Keep `source_text` and `source_label` tied to the supplied `--source-file`.
- Resolve the compile/staging unit separately:
  - `src/...` sources use themselves.
  - `build/diagnostics`, `build/mwcc_debug_cache`, and external retained sources
    resolve to the live `src/...` unit from `_find_unit_for_function`.
- Fail early with a clear CLI error if a retained source needs full-TU staging
  but no live `src/...` unit can be resolved.
- Preserve the issue 1101 retained-source and pcdump/compile-metadata evidence
  contract.

## Regression Coverage

- The diagnostics retained-source test now asserts generated probes compile
  with `unit_source == live_source`, not the diagnostics retained source.
- The same test verifies the retained generated probe source remains under
  `build/mwcc_debug_cache` and the emitted compile command uses the live
  `--unit-source`.
- Existing out-of-repo retained full-TU and transform full-unit tests continue
  to cover the older source paths.
