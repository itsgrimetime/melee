# MWCC debug feedback - 2026-05-20

Context: working on `src/melee/mn/mnvibration.c`, mainly `fn_80247510` and
`fn_80248A78`; later also `fn_802487A8`.

## Issues

- `melee-agent debug pcdump-local --diff` appears to choose the wrong function
  in this TU. Running it for forced `fn_80247510` selected
  `mnVibration_JObjGetTranslationX` and failed with
  `could not find function 'mnVibration_JObjGetTranslationX' in report.json`.
  A `--function/-f` option on `pcdump-local --diff`, or forwarding the
  `--force-phys-fn` function when present, would make one-shot force proofs
  usable in multi-function TUs with static inlines.

- `python tools/checkdiff.py <fn> --no-build --no-tty --format json` prints
  useful JSON, then exits through an `UnboundLocalError`:
  `cannot access local variable 'result' where it is not associated with a value`.
  The JSON is still parseable through `jq`, but the non-zero traceback makes
  scripts treat successful no-build diffs as failures.

- `suggest-coalesce-source --discover` can propose useful-looking pairs where
  both virtuals are compiler temps, but pair mode often returns no source
  suggestions. For `fn_80247510`, it found `53=92`; for `fn_80248A78`, it found
  `49=70` and `70=41`. In all cases the first-def/use-block IR facts were
  helpful, but I still had to manually grep the pcdump blocks. A source-nearby
  snippet or "nearest C statement" fallback for unmapped compiler temps would
  make this much more actionable.

- Forcing the `fn_80247510` discovered coalesce `53=92` with
  `--force-coalesce-fn fn_80247510 --force-coalesce 53=92` produced a pcdump
  that starts `fn_80247510` but stops before an object is emitted. There was no
  clear diagnostic in the dump explaining whether the pair is invalid,
  interfering, out of range for that coalesce pass, or a DLL-side crash.

- After `ad21e50e4`, `fn_80247510` discover found more multi-holder pairs
  starting with `36=38`. Forcing `36=38` hit the local hang guard as well
  (`MWCC_DEBUG_HANG_TIMEOUT=20`), producing only a pcdump and no object. The
  new pair enumeration is useful, but several first-choice pairs still need a
  better invalid-pair diagnostic or a safer dry-run validator.

- For `fn_80248A78`, `--force-coalesce 49=70` triggered the local hang guard:
  `no compile progress for 45s - likely wibo hang (UE state)`. The dump still
  existed but no `.o` was produced. `--force-coalesce 70=41` and
  `--force-coalesce '49=70,70=41'` completed and logged forced aliases, but
  also did not leave the requested `--keep-obj` file. It would help if
  `pcdump-local` warned when `--keep-obj` was requested but no object was
  available, even when the pcdump itself completed.

- After `ad21e50e4`, `suggest-coalesce-source --discover` found a new
  `fn_80248A78` common-subexpr pair `46=50` with useful evidence
  (`lwz 80(r51)` in blocks 107 and 83). However,
  `pcdump-local --force-coalesce-fn fn_80248A78 --force-coalesce 46=50`
  also hit the 45s local hang guard and produced no object. This is useful
  source guidance, but not yet a force proof.

- The same `fn_80248A78` force-coalesce pair (`46=50`) completes on the remote
  Windows path with `debug pcdump --branch wip/mn-heartbeat --force-coalesce`.
  The local-only hang therefore looks wibo/local-runtime-specific, not
  necessarily an invalid coalesce pair. The resulting pcdump changes a large
  portion of the allocator graph, though, so a direct common-subexpression
  source change is still not obviously target-shaped.

- `enumerate-decl-orders` only considered top-level locals in `fn_80248A78`
  (`frame`). The interesting register swaps are in the nested cursor-setup
  block (`cursor_gobj`, `cursor_jobj`, `row_0_jobj`, `row_1_jobj`,
  `cursor_row`, etc.), so nested block-local support would target the actual
  problem space.

- The checked-in `mwcc-debug` skill text is now stale in two important ways:
  it documents local mode at the top, but the Limitations/Troubleshooting
  sections still say macOS local mode is broken and remote committed code is
  required. It also does not document newer commands like
  `suggest-coalesce-source`, `var-to-virtual`, `virtual-to-var`,
  `score-source`, `mutate`, `tier3-search`, or function-scoped force options.

- Several cache-aware commands reported
  `[mwcc_debug] using stale cached pcdump (mnvibration.c modified since cache)`
  immediately after `pcdump-local` refreshed `build/mwcc_debug/mnvibration.txt`
  and synced it to `build/mwcc_debug_cache/melee/mn/mnvibration.txt`. This may
  be a false positive from timestamp comparisons or from edits reverted back to
  identical source. It would help to include the source/cache mtimes in the
  warning or add a `--refresh` flag to commands like `rank-callees` and
  `suggest-coalesce-source`.

- `pcdump-local` syncs forced experimental dumps into the shared
  `build/mwcc_debug_cache/...` path. After running a scoped force-phys or
  force-iter experiment for `fn_80248A78`, follow-up commands that auto-resolve
  the cache can read the forced allocation as if it were the natural baseline.
  It would be safer to skip cache sync when any `--force-*` option is present,
  or to tag the cache entry as forced so later commands refuse it unless
  explicitly requested.

- The new bridge/mutation helpers appear to miss nested block locals. In
  `fn_80248A78`, `var-to-virtual -f fn_80248A78 cursor_row` and
  `row_0_jobj` reported "variable not found", and
  `mutate insert-alias --var cursor_row` failed the same way. Worse,
  `virtual-to-var -f fn_80248A78 34` returned low-confidence `frame`, but
  the pcdump and source context show the disputed virtual is really the nested
  `cursor_row`-style value in the cursor setup block. For this TU, nested-local
  awareness is the main difference between useful and misleading guidance.

## Useful signals from the new tooling

- `fn_80247510`: force-targeting the expected head registers improves hunk
  count from 34 to 28 but keeps match at `92.0764%`, so the remaining mismatch
  is not just allocator choice. `guide` against the forced target narrowed the
  natural allocator disagreement to `r50` wanting `r30` and `r47` wanting `r29`.

- `fn_80248A78`: opcode similarity is already `1.0`; the visible mismatch is a
  local cursor-setup register/lifetime swap. The top diff shows expected
  `row_0_jobj` in `r26` and `cursor_row` in `r29`, while current has them
  swapped early and then cascades through `r28`/`r29` temp use later.

- `fn_802487A8`: forcing a plausible target register subset collapses the
  register cascade from 13 hunks to 6, but still leaves `line_delta=1` and the
  second-loop preheader in the wrong order. The remaining target shape is:
  `port_b = 0`, load `f31`, materialize `HSD_PadCopyStatus`, compute
  `mnVibration_804D4FE8 + (port_b << 1)`, then keep a zero-extended port alias
  for pad/table indexing. Source attempts for explicit indexed pointer init and
  a `u8` port alias were neutral or regressed, so this looks like a source
  structure issue rather than pure allocator choice.

- `fn_802487A8`: after the multi-holder update, discover found `56=74`.
  `pcdump-local --force-coalesce-fn fn_802487A8 --force-coalesce 56=74`
  completed but did not write the requested `--keep-obj` file and emitted no
  warning about the missing object.
