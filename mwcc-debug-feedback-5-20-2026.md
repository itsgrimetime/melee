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

- After merging `20045b280`, `python tools/checkdiff.py fn_802487A8 --no-build
  --format json` still exits 1 with the same `UnboundLocalError` after writing
  valid JSON. The fix appears not to cover the no-build JSON return path yet.

- After merging `20045b280`, `tier3-search -f fn_802487A8 --include-low-confidence`
  still generates seeds that fail before mutation/permutation because the
  staged full-TU source cannot open `#include "mnvibration.h"`. The compile
  error points at line 1 of `tier3_seed_*/base.c`. The existing
  `fix-perm-compile` wrapper says `already-fixed`, but it only stages the
  candidate under `nonmatchings/.permuter_stage_$$.c`; for full-TU candidates,
  that loses the original `src/melee/mn` quote-include search directory. A
  source-dir include (`-i src/melee/mn`) or staging the candidate at the
  original relative TU path would unblock these seeds.

- `verify-with-name-magic` successfully renames `mnVibration_80248444`'s
  anonymous constants (`@465 -> mnVibration_804DC018`,
  `@513 -> mnVibration_804DC030`, `@539 -> mnVibration_804DC034`), but
  `checkdiff` still reports a mismatch because the relocation offsets differ
  by `+2` for the renamed SDA21 relocs (for example expected `+0xc0`, current
  `+0xc2`). The function is classified as `relocation-label-only` with
  `opcode_similarity=1.0` and `line_delta=0`, so this looks like a relocation
  offset/postprocess gap rather than source codegen.

- On the new `fn_80247510` baseline, `suggest-coalesce-source --discover`
  found the retained `next_row` virtual as an end-of-chain pair (`34=39`).
  Forcing `34=39` still hit the local wibo hang guard, but the latest tooling
  now correctly warns that `--keep-obj` produced no object and skips syncing
  the forced dump into the baseline cache. That addresses the earlier silent
  forced-cache contamination failure mode.

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

## Follow-up after merging `365b7bd5c`

- `python tools/checkdiff.py fn_802487A8 --no-build --format json` no longer
  tracebacked after emitting JSON. It now exits non-zero for a real mismatch,
  which is expected, and the JSON stays cleanly parseable. This fixes the
  earlier `UnboundLocalError` path for my local workflow.

- `tier3-search -f fn_802487A8 --include-low-confidence` now gets past the
  full-TU include-path failure. The type-change seeds compile and can be
  verified against the real source. I verified the new
  `anim_byte_chain: u8 -> u32` seed with `verify-perm`; it transferred cleanly
  but was neutral (`95.916664%`, delta `+0.0`).

- The remaining `tier3-search` alias seeds still fail because the generated
  declarations are inserted after executable statements in this C89/MWCC
  context. Examples from `fn_802487A8`:
  `HSD_JObj* port_indicator_alias = port_indicator;`,
  `MnVibrationData* data_alias = data;`, and
  `void* walker_b_clear_alias = walker_b_clear;` all produce expression-syntax
  errors. Hoisting declarations to the block top, or emitting a declaration at
  block top plus a later assignment, should make these seeds testable.

- `pcdump-local` forced runs now correctly skip baseline cache sync, and the
  local hang guard gives a useful diagnostic for `--force-coalesce 46=50` on
  `fn_80248A78`. That closes the earlier silent forced-cache contamination
  failure mode.

- `--force-phys` still needs a class-scoped variant or a clearer class filter.
  On `fn_80248A78`, forcing `--force-phys 50:26,36:29` with
  `--force-phys-fn fn_80248A78` logged two force applications per ig_idx inside
  the same function, for example `ig_idx=50: r29 -> r26` and later
  `ig_idx=50: r0 -> r26`. The resulting diff looked structurally corrupted,
  which makes the force proof hard to trust. A `class:ig_idx:phys` form, or
  refusing GPR phys registers on non-GPR classes, would make this safer.

- Commands that temporarily patch and restore the source (`enumerate-decl-orders`,
  `tier3-search`, `verify-perm`) update the source mtime even when content is
  restored. Follow-up debug commands then warn that the freshly generated cache
  is stale (`src` newer than `cache`) despite identical source content. A
  content-hash freshness check, or preserving/restoring mtimes for no-keep
  experiments, would reduce false stale-cache warnings.

- `tier3-search` still reports that per-seed permuter runs are not wired in v1.
  The seed generation is useful now that the include path is fixed, but the
  manual `verify-perm`/permuter handoff is still the slow part.

## Follow-up after merging `314fcc4ef`

- The new class-scoped `--force-phys` syntax works as intended. Re-running the
  old ambiguous `fn_80248A78` hypothesis with
  `--force-phys 'gpr:50:26,gpr:36:29'` no longer double-applied the same ig_idx
  to FP and GPR colorgraphs. The force still did not reach target text, which is
  a useful source-shape signal: the visible row-0-JObj/cursor-row register swap
  is not sufficient on its own.

- `suggest-casts --asm --signedness` was useful as a quick negative filter on
  `fn_80248A78`, `fn_802487A8`, `fn_80247510`, and `mnVibration_80248444`.
  It found no signedness mismatches in the current diffs. The only nearby
  `fn_802487A8` candidate, splitting
  `(f32) (anim_byte_chain = data->x0[port_a + 2])` into assignment plus call,
  transferred cleanly but was neutral (`95.916664%`, delta `+0.0`).

- `verify-with-name-magic` direct anonymous-symbol mapping now works for the
  4-byte float constants in `mnVibration_80248444`: `@513` and `@539` can be
  renamed to `mnVibration_804DC030` and `mnVibration_804DC034`. After also
  mapping `u32=mnVibration_804DC018`, the remaining diff is only relocation
  site offsets (`+0xc0` vs `+0xc2`, and similar) even when the symbol names now
  match. A relocation-line normalizer that treats relocations on the immediate
  halfword as belonging to the containing instruction would let this
  opcode-identical function be reported as matched/noise-only.

- Trying to source-reference the named float globals directly in
  `mnVibration_80248444` (`mnVibration_804DC030`/`804DC034` instead of `0.0f`/
  `0.03f`) regressed badly (`100.0%` fuzzy to `94.33594%`), so the right source
  is still the literal form plus post-build/name-magic-style normalization.
