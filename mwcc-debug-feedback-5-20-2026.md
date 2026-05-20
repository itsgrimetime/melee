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

## Follow-up from the `fn_802487A8` 98.36% baseline

- A stronger class-scoped force proof now gets `fn_802487A8` very close to
  target text. Forcing
  `gpr:32:30,gpr:45:31,gpr:73:23,gpr:47:23,gpr:48:25,gpr:79:28,gpr:106:29,gpr:53:26,gpr:55:24,gpr:51:27`
  leaves only the expected relocation-name noise plus two real source-shape
  gaps: the `mnVibration_804D4FE8` SDA base temp is still separate from
  `idx_ptr`, and MWCC does not naturally keep a long-lived zero-extended port
  alias for both `HSD_PadCopyStatus[port]` and the later
  `mnVibration_804D4FE8[port]` lookup.

- `--force-coalesce-fn fn_802487A8 --force-coalesce 48=50` now produces a
  useful local hang diagnostic instead of silently contaminating the cache. The
  diagnostic pointed at an invalid/interfering pair; `debug analyze --json`
  confirms baseline virtuals `48` (`idx_ptr = base + offset`) and `50`
  (`mnVibration_804D4FE8` SDA base) currently interfere. That means the source
  problem is not just "force these two together"; the C has to avoid creating
  the separate live base temp in the first place.

- `tier3-search` is improved after the C89 alias-split update: four of six
  generated `fn_802487A8` seeds compiled. Real-tree verification found no
  source wins: `data` alias regressed (`98.36% -> 96.58%`), `anim_byte_chain`
  `u8 -> u32` and `port_b_alias s32 -> u32` were neutral, and
  `anim_byte_chain u8 -> s8` regressed hard. The two remaining alias seeds now
  fail with definite-init diagnostics (`port_indicator` and
  `gobj_user_data_alias` "not initialized before being used"), so alias seed
  generation still needs to avoid aliases of locals before their first
  assignment.

## Follow-up during `mnvibration-decomp` heartbeat at 2026-05-20 06:00 PT

- `pcdump-local --force-coalesce-fn fn_80248A78 --force-coalesce 46=50`
  still hits the local hang guard and produces no object. The new diagnostic is
  much better than before, but its suggested next step says to run
  `debug analyze --cg`; `melee-agent debug analyze --help` does not expose a
  `--cg` option. Either the option is missing from the CLI or the diagnostic
  should point at an existing command.

- `verify-with-name-magic -f mnVibration_80248444 -m
  's32=mnVibration_804DC018,@538=mnVibration_804DC034,@512=mnVibration_804DC030'`
  renamed `@481 -> mnVibration_804DC018`, but the active diff still used `@464`
  for the signed int-to-float bias. Direct mapping
  `@464=mnVibration_804DC018` fixed the label. When multiple anonymous symbols
  share the same value, the value alias (`s32=`) may choose the wrong one for
  the function being checked; a warning listing all matching anonymous symbols
  would make this less surprising.

- After direct name-magic mapping for `mnVibration_80248444`, all anonymous
  constant labels were fixed, but checkdiff still reported mismatch solely from
  SDA21 relocation annotation offsets (`expected +0xc0`, current `+0xc2`, etc.).
  That is useful confirmation that the remaining issue is relocation-offset
  normalization/postprocessing, not source codegen or constant naming.

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

## Follow-up after merging `dd911094f`

- Positive: `--force-phys-iter` is now good enough to prove the remaining
  `fn_80248A78` register cascade. Forcing class 0 iters
  `42/44/46 -> r28`, `55/57/58/59 -> r26`, `66 -> r29`, plus class 1 iter
  `14 -> f29` (phys 29), makes the function instruction/register-identical to target.
  The remaining diff is only relocation-line offset/name noise. That is a much
  stronger signal than the prior coarse match percentage: the current source is
  structurally viable, and the unresolved work is natural C for the allocator
  ordering around the cursor-row/jobjs[17] block.

- Regression/bug: class-scoped `--force-phys` appears to apply to both GPR and
  FP colorgraphs again on `fn_80248A78`. Repro:
  `pcdump-local src/melee/mn/mnvibration.c --force-phys
  'gpr:50:26,gpr:36:29' --force-phys-fn fn_80248A78`. The dump logs both
  class 0 applications (`ig_idx=50: r29 -> r26`, `ig_idx=36: r0 -> r29`) and
  class 1 applications (`ig_idx=50: r0 -> r26`, `ig_idx=36: r30 -> r29`).
  The class/iteration form did not have this problem, so `--force-phys-iter`
  is the reliable workaround for now.

- `guide` with a target derived from the successful force-iter run is useful:
  it correctly identifies `r34` as the cursor-row virtual wanting `r29` while
  `r50/r68` occupy it, and points at alias/lifetime changes around repeated
  `jobjs[17]` loads. Manual source tests this round were neutral or regressed
  and were reverted: moving `cursor_row` to function scope regressed to
  `99.31899%`, moving its nested declaration was neutral, changing it to `u32`
  was neutral, removing `row_0_jobj` was neutral, and chained-initing the row
  value inside the `(f32)` cast regressed to `98.22222%`.

- `tier3-search -f fn_80248A78 --target <forced-target>` still reports "no
  Tier 3 targets" even though `guide` has a concrete alias-split/lifetime
  diagnosis involving compiler temps `r46/r50` (`lwz 80(r51)`) and `r34`. It
  would be useful if Tier 3 could seed mutations from `suggest-coalesce-source
  --discover`/`guide` compiler-temp facts, not only source variables that the
  current symbol bridge can bind.

- The `dd911094f` alias mutator fixes are partial. `tier3-search` on
  `fn_802487A8` now has some alias seeds that compile, for example the `data`
  alias seed, but aliases of locals whose first real value is assigned later
  still initialize too early and fail with "variable X is not initialized
  before being used" (`port_indicator`, `walker_b_clear`,
  `gobj_user_data_alias`). Declaring the alias at block top but assigning it
  immediately after the original local's first real definition would make these
  seeds testable.

- Another alias-mutator edge case: `tier3-search` on `fn_80247510` generated
  invalid member syntax for the `jobjs` seed (`->jobjs_alias[23]`). The alias
  rewriter needs to distinguish aliasing a local pointer from aliasing a field
  name inside `data->jobjs`.

## Heartbeat follow-up at 2026-05-20 05:00 PDT

- The checked-in `mwcc-debug` skill says `virtual-to-var` supports `--basis`,
  but the CLI rejects it (`No such option: --basis`). `var-to-virtual --basis`
  works. For nested-local-heavy functions like `fn_80248A78`, inverse bridge
  evidence would be useful because `virtual-to-var r34` currently returns the
  low-confidence top-level `frame` guess while the relevant value is in the
  nested cursor setup block.

- `verify-perm`/`triage-perm` build-failure output is still too filtered for
  interesting failed candidates. During a short `debug permute` run on
  `fn_80248A78`, lower byte-score candidates such as `output-3650-2` and
  `output-3665-6` failed real-tree transfer, but `verify-perm` only surfaced:
  `#   Error:           ^^^^^^^^^`. Including the first full compiler
  diagnostic with filename/line, or preserving a temporary failing source path
  on request, would make it possible to repair promising candidates instead of
  manually re-running/inspecting them.

- `debug permute` is useful with the new per-PID pcdump scorer, but extra
  upstream permuter args need an explicit `--` separator. Without it,
  `melee-agent debug permute -f fn_80248A78 --best-only` fails because Typer
  consumes the upstream permuter flag. A note in the help example would save
  one failed launch.

## Heartbeat follow-up at 2026-05-20 07:10 PDT

- `debug ceiling fn_80247510` reported "PROBABLE CEILING" after cast and
  decl-order checks, but the next `debug stuck`/`virtual-to-var` pass exposed a
  concrete source-shape lead: all four unexpected SPILLED virtuals were
  compiler-created `li 255` temps from the inlined `mnVibration_GetNameSlot`
  sentinel paths. It would be useful if `ceiling` optionally ran the same
  virtual-to-source fallback for SPILLED nodes and surfaced "try sentinel/return
  shape around this inline" before calling ceiling.

- `match-iter-first` on `fn_80247510` returned an ambiguous target list
  (`146,52,49,148,41`). Feeding that list to `--force-iter-first` or forcing the
  corresponding phys regs did not move toward a clean target and disturbed
  early code. The output already labels these as ambiguous; a follow-up
  "verify this with pcdump-local --diff before trusting it" note, or an
  integrated dry-run score, would make the failure mode clearer.

- `pcdump-local` has function scoping for `--force-phys` and
  `--force-coalesce`, but the help does not show a function-scoped equivalent
  for `--force-iter-first`. If that support exists, it should be exposed; if it
  does not, it is risky in multi-function TUs because the forced iteration list
  can apply outside the target function.

## Heartbeat follow-up at 2026-05-20 07:45 PDT

- `pcdump-local --help` now exposes `--force-phys-iter` and `--force-phys-fn`,
  and says `--force-phys-fn` scopes both `--force-phys` and
  `--force-phys-iter`. That closes the force-by-iteration scoping gap, but the
  help still does not clearly say whether `--force-iter-first` is scoped by the
  same function option. The skill text implies using function scoping for
  force-iteration work, so the CLI help should explicitly confirm or deny this.

- `melee-agent debug root-identity` is not available in this checkout
  (`No such command 'root-identity'`). If root-identity probing was shipped
  under another command name, the skill/help should point to it; if it was not
  shipped yet, this is still a gap for proving coalesce/root hypotheses.

- `suggest-coalesce-source --discover` on `fn_802487A8` produced one candidate
  pair, `55=73`, with no source suggestions. Forcing that exact pair with
  `--force-coalesce-fn fn_802487A8 --force-coalesce 55=73` hung local wibo until
  the 45s watchdog killed it. The watchdog message is helpful, but
  `suggest-coalesce-source` should ideally preflight whether a discovered pair
  is known-dangerous/interfering before presenting it as the only candidate.

- `tier3-search` on `fn_802487A8` generated four seed plans and found two
  compiling width-change seeds, but then stopped with "Per-seed permuter runs
  not yet wired in v1." The command help still describes a full workflow that
  runs `debug permute` for each compiling seed and reports the best result, so
  the implementation and help are out of sync.
