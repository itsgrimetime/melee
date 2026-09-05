# select-order-search residuals and restore plan

## Task 1: regression tests

- Add a CLI regression proving `debug select-order-search --no-score-match-percent` restores the live source file even when `compile_source_variant` mutates it during a generated probe compile.
- Add a CLI regression proving `--force-phys` plus residual analysis annotates top ranked successful candidates with candidate-specific first-divergence data and retained source paths.
- Verify the new tests fail against the pre-fix command behavior.

## Task 2: source restore guard

- Resolve the live source path for `select-order-search` candidates from `--source-file` or `_find_unit_for_function`.
- Wrap the complete `.c` candidate scoring path in byte-based live-source snapshot and restore verification.
- Preserve the original live-source bytes to `build/source-restore-backups/` and surface that path if restore fails.
- Ensure restore failures become failed variant diagnostics and preserve `source_retained`.

## Task 3: residual first-divergence output

- Add `--force-phys` and `--residual-first-divergence-top` options.
- Store successful candidate pcdump text in memory without relying on unique labels.
- After ranking, attach residual summaries to top successful candidates when enabled.
- Include gated allocator facts, optional source ideas, objective status, opcode/frame status, and retained source path.
- Render residual summaries in text output and JSON.

## Task 4: verification and integration

- Run the targeted select-order-search tests.
- Run CLI help smoke for the new options.
- Request independent code review.
- Commit the spec, plan, tests, and implementation.
- Resolve issues #771 and #772 with the commit hash.
- Refresh the editable `melee-agent` install and verify `/opt/homebrew/bin/melee-agent` imports the current master code.
