# MWCC debug feedback - 2026-05-21

Context: continuing work on `src/melee/mn/mnvibration.c`, focused on
`fn_80247510`'s cursor-position setter mismatch after merging
`80027558c` (`mwcc-debug: add copy tracing diagnostics`).

## Issues

- `trace-copy` is immediately useful, but the virtual-to-colorgraph mapping
  can pick the wrong register class when the same visible virtual number exists
  in both class 0 and class 1. In the X-only cursor setter temp experiment,
  `trace-copy -f fn_80247510 --from r50 --to r108` correctly found
  `mr r108,r50`, but the reported source mapping resolved `r50` to class 1
  with physical `r0`. The relevant source virtual is the GPR cursor pointer
  loaded by `lwz r50,40(...)`, which should resolve to class 0 and physical
  `r31`. `virtual-to-ig`/`trace-copy` should either accept `--class gpr|fp` or
  prefer the class implied by the defining opcode (`lwz`/`mr` GPR copy vs FP
  op), and print a warning when multiple class candidates exist.

- `trace-copy` currently reports the copied pointer as
  `removed-before-coloring`, with last sighting at `AFTER PEEPHOLE FORWARD`.
  That is already a strong signal, but the next useful detail would be the
  exact first pass where the copy is absent and the likely transform category:
  copy propagation, dead-copy elimination, coalescing before IG construction, or
  rewrite/lowering. For `fn_80247510`, the key question is whether the copy dies
  because `r108`'s only use is substituted with `r50`, or because the temp never
  becomes an interference-graph node.

- `trace-copy` requires knowing both sides of the copy ahead of time. A
  discovery mode would fit this workflow better, for example
  `debug trace-copy -f fn_80247510 --involving r50 --near-block 245` or
  `--list-copies`. The manual loop right now is: grep pcdump for likely `mr`
  lines, then trace each one. The tool could cheaply list all copies involving
  a virtual, their first/last pass, and whether each survives to colorgraph.

- The checked-in `mwcc-debug` skill now says `suggest-inlines` pattern seeds
  understand visible `HSD_JObjSetTranslateX/Y/Z` calls as hiding
  `HSD_JObjSetMtxDirtySub`, but in this checkout
  `suggest-inlines -f fn_80247510 --seed-source patterns --budget 80` still
  produced only generic return-helper candidates. It did not suggest the
  cursor-copy/dirty-call lifetime split around the three
  `HSD_JObjSetTranslate*` calls in `mnVibration_SetCursorPosition`.
  `--verify` also only verified those generic return helpers.

- A copy-preservation force proof still appears to be missing. There is no
  `--force-no-coalesce` or `--force-copy-survives` equivalent in
  `pcdump-local --help`. For this blocker, forcing final physical registers is
  less useful than proving whether preserving the specific `mr r108,r50` copy
  would create the target `mr` instructions. A no-coalesce/copy-survival force
  mode would let us distinguish "find a natural lifetime barrier" from "the
  source shape is still wrong before the copy."

- `pcdump-local` syncs ordinary unforced temporary source experiments into the
  baseline cache. That is correct mechanically, but in this workflow it is easy
  to contaminate follow-up commands with an intentionally reverted probe. A
  `--no-cache-sync` option, or a warning when syncing while the source file has
  uncommitted changes, would reduce the need to manually refresh a clean dump
  after every failed experiment.

## Useful signals from the new tooling

- The X-only pointer-temp helper did introduce the exact PCode copy we expected:
  `mr r108,r50` appears from `BEFORE GLOBAL OPTIMIZATION` through
  `AFTER PEEPHOLE FORWARD`. `trace-copy` then showed that `r108` is `pcode-only`
  and does not survive into simplify/colorgraph. This proves the failed helper
  is not an allocator problem; the copy is gone before register coloring.

- The matched sibling `fn_80248A78` is a useful reference case for the same
  pattern. `trace-copy` reports `r68 <- r37`, `r66 <- r37`, and `r64 <- r37` as
  `copy-survived-distinct-phys`, with the source colored to `r27` and the temp
  copies colored to `r29`. That gives us a concrete target shape for a
  source-level lifetime barrier.

- Adding an X-only float value temp alongside the pointer temp was a negative
  result: it regressed the frame from `-280` to `-264`, reduced the emitted
  function size, and did not introduce the desired `r108 <- r50` copy at all.
  This rules out the naive "copy both pointer and value" local helper shape for
  `fn_80247510`.

## Follow-up after `19e6ebb38`

Context: merged `19e6ebb38` (`mwcc-debug: refine copy tracing followups`) into
`wip/mn-heartbeat` and reran the diagnostics against `fn_80247510`.

### Improvements that helped

- `trace-copy --class gpr` fixes the earlier class-confusion problem. Re-running
  the old X-only cursor temp dump now correctly reports `r50` as the GPR cursor
  pointer. The stronger result is: source `r50` reaches simplify only, the copy
  destination `r108` is pcode-only, and the copy disappears before any colorgraph
  decision. That is the precise evidence we needed.

- `trace-copy --list-copies`, `--involving`, and `--near-block` are useful. The
  baseline has no copy involving `r50` around block 245, while the dirty-copy
  source probes do expose `r50 -> temp` copies at that exact block.

- `pcdump-local --no-cache-sync` works and is very helpful for source probes.
  It let temporary inline experiments stay out of the canonical pcdump cache.

### Remaining issues / new requests

- `suggest-coalesce-source --discover` surfaced a plausible cascade target:
  `34 -> 50` as the final pair in the current `31,30,29,28,27` cascade. Pair
  mode maps `r34` to `inputs_repeat` with low confidence, but `r50` falls back
  to the defining IR op `lwz r50,40(...)`. No source suggestion was produced for
  the important `34 -> 50` pair, so the result is useful as a direction but not
  directly actionable yet.

- The preflight for `--force-coalesce` still misses at least one hang case:
  `pcdump-local ... --force-coalesce "34=50" --force-coalesce-fn fn_80247510`
  hung locally even though `suggest-coalesce-source` marked the pair safe. A
  timeout, dry-run preflight, or stronger invalid-pair detector would make this
  safer to use during active iteration.

- `suggest-inlines --seed-source patterns --budget 80` still only produced
  generic return-helper candidates for `fn_80247510`; it did not propose the
  cursor `HSD_JObjSetTranslate*` / dirty-call lifetime split. `--seed-source
  coalesce` returned no candidates. This is still the biggest missing source
  suggestion for this function.

- One `suggest-inlines --json` patched-source payload was visibly malformed
  while showing return-helper candidates, with tokens like `ininputs` and
  `naname_idx` in the patched source. I did not apply it, but this looks like
  a source-splice bug worth guarding in verification.

- Direct `python configure.py && ninja` and direct `python tools/checkdiff.py
  fn_80247510 --no-tty --format plain` both got stuck in a configure/ninja path
  in this worktree. `debug guide --asm-hunks` still managed to show hunks, so
  this may be an adjacent build/checkdiff issue rather than debugger-specific,
  but any debugger command that shells out to checkdiff should have a timeout
  and clear failure mode.

### Source-shape evidence

- All-axis and outer-scope `dirty_jobj = cursor_jobj` cursor setter probes both
  create the expected early copy at block 245 (`r50 -> r110` in the current
  numbering), but `trace-copy` reports the destination as pcode-only and the
  source as simplify-only. The copy still does not become a colorgraph node.

- Those dirty-copy probes also cause a broad allocator cascade: `r49/r50` are
  removed from the baseline colorgraph and many callee-save assignments shift.
  That is not a local register nudge; it is a structural regression. The probes
  were reverted.

## Follow-up after `3494375bf`

Context: merged `3494375bf` (`mwcc-debug: fix source-shape feedback
regressions`) into `wip/mn-heartbeat` and reran the diagnostics against
`fn_80247510`.

### Improvements that helped

- `suggest-inlines --seed-source patterns` now finds the relevant hidden
  dirty-call source shapes first. The top candidates are the X/Y/Z
  `HSD_JObjSetTranslate*` calls in `mnVibration_SetCursorPosition`, each
  described as a short-lived argument temp for the hidden
  `HSD_JObjSetMtxDirtySub` call.

- The candidate scope is now correct: the suggestions point at
  `mnVibration_SetCursorPosition`, not unrelated local names in
  `fn_80247510`.

- Default `--json` output is now compact. Full `patched_source` is emitted only
  with `--emit-patches`, and the earlier malformed splice tokens like
  `ininputs` / `naname_idx` did not reappear in this run.

- `suggest-inlines --verify --checkdiff-timeout 10` compiled the dirty-call
  candidates without hanging. The three single-axis candidates each scored
  `97.14597`, so they are valid probes but do not improve the current function
  by themselves.

- `pcdump-local --diff -f fn_80247510 --checkdiff-timeout 5` also returned
  promptly and produced a useful objdiff. The integrated diff path is now usable
  for this function, where direct checkdiff/build commands had previously been
  easy to wedge.

- The new `pcdump-local` compile watchdog works when configured with
  `MWCC_DEBUG_HANG_TIMEOUT`. Re-running the bad
  `--force-coalesce "34=50"` probe with `MWCC_DEBUG_HANG_TIMEOUT=8` returned
  after about ten seconds and printed a clear diagnostic instead of trapping the
  session indefinitely.

### Remaining issues / new requests

- `suggest-coalesce-source --discover` still marks `34 -> 50` safe and
  actionable even though `pcdump-local --force-coalesce "34=50"
  --force-coalesce-fn fn_80247510` still hangs the compiler. `debug analyze`
  confirms `r34` and `r50` do not directly interfere in the baseline graph, so
  the current direct-interference preflight is understandable but insufficient.
  This likely needs a stronger "forceability" preflight or an optional dry-run
  path that can reuse the watchdog and report "non-interfering but unsafe to
  force."

- The watchdog diagnostic currently exits successfully and writes a partial
  pcdump. For scripted workflows, a watchdog-triggered compile should probably
  return non-zero or include a machine-readable status so callers do not treat
  the partial dump as a valid forced proof.

- `suggest-inlines --verify` reports `checkdiff_delta: null` and no baseline
  percent. For this workflow, it would be more useful to print the baseline
  score, candidate score, and delta, even when the candidate merely ties the
  baseline.

- The emitted dirty-temp patch uses a generic `void* cursor_jobj_arg_temp` and
  inserts the declaration at the patch site. It compiles, but source candidates
  would be easier to evaluate and upstream if they preserved the apparent
  source type (`HSD_JObj*`) and followed the local declaration-at-top style.

- The hidden dirty-call suggestions are single-axis. A grouped candidate for
  applying the same temp strategy to X/Y/Z together would be helpful, because
  the target mismatch involves the repeated dirty-call copy pattern across all
  three translation setters.

### Source-shape evidence

- Manually applying the grouped X/Y/Z dirty-temp shape produced the expected
  early `mr r110,r50` copy at block 245. `trace-copy --list-copies --involving
  r50 --near-block 245` still reports the destination as `pcode-only`, with the
  copy eliminated before coloring. That means the newly suggested temp shape is
  a good diagnostic lead, but it is not yet the natural lifetime barrier needed
  by the target.

- The grouped temp shape also regressed the frame from `-280` to `-288` and
  caused a broad register cascade. This is further evidence that the current
  hand-written dirty-temp rewrite is not the final source structure.

## Follow-up after `d7108027c`

Context: merged `d7108027c` (`mwcc-debug: address fn_80247510 feedback`) into
`wip/mn-heartbeat` and reran the diagnostics against `fn_80247510`.

### Improvements that helped

- `suggest-coalesce-source --discover` now correctly marks the whole cascade as
  unsafe to force when no direct copy/identity edge exists. The important
  `34 -> 50` pair now reports:
  `no direct copy/identity edge between r34 and r50 in pre-coloring IR`.
  This resolves the misleading "safe" preflight from the prior run.

- `suggest-inlines --seed-source patterns` now includes
  `hidden-dirty-arg-temp-group-0004`, the grouped X/Y/Z dirty-temp candidate
  for `mnVibration_SetCursorPosition`.

- The generated dirty-temp source now uses the apparent type
  `HSD_JObj* cursor_jobj_arg_temp` and keeps declarations before executable
  statements. That fixes the earlier `void*` / declaration-placement concern.

- `suggest-inlines --verify --checkdiff-timeout 10` now reports baseline,
  candidate, and delta. For the three single-axis candidates and the grouped
  candidate, the score was `97.14597 -> 97.14597` with `delta=0.0`.

- `pcdump-local` now returns exit status `124` when the watchdog kills the bad
  forced coalesce run. That makes the partial dump distinguishable from a valid
  force proof in scripts.

### Remaining issues / new requests

- The grouped dirty-temp candidate ties checkdiff but still does not tell us
  whether its introduced copy survives or dies before coloring. A useful next
  layer would be an optional `suggest-inlines --trace-copies` / `--explain`
  mode that, for verified candidates, runs `trace-copy` on newly introduced
  `mr` copies and reports whether each copy reached simplify/colorgraph.

- `--emit-patches` is useful but hard to inspect because each `patched_source`
  JSON string is the full TU on one line. A compact `--emit-diffs` or
  `--emit-hunks` mode would make candidate review much faster, especially for
  large TUs like `mnvibration.c`.

### Source-shape evidence

- The new grouped dirty-temp candidate is confirmed as a no-gain source shape:
  it compiles cleanly and ties the current baseline (`delta=0.0`). Based on the
  earlier manual grouped probe plus `trace-copy`, this still looks like a
  pcode-only copy eliminated before coloring, not the missing natural lifetime
  barrier.

## Follow-up after `b64403c36`

Context: merged `b64403c36` (`mwcc-debug: trace inline candidate copies`) into
`wip/mn-heartbeat` and reran the inline diagnostics against `fn_80247510`.

### Improvements that helped

- `suggest-inlines --json --emit-hunks` works well. It emits compact unified
  hunks for each candidate without the one-line full-TU `patched_source`
  payload, which makes reviewing large-TU candidates much faster.

- `suggest-inlines --verify --trace-copies` now automatically proves the key
  dirty-temp source-shape result. The grouped candidate still ties baseline
  (`97.14597 -> 97.14597`, `delta=0.0`), and its introduced cursor copies:
  `r50 -> r110`, `r50 -> r109`, and `r50 -> r108` are all reported as
  `removed-before-coloring` / `copy-eliminated-before-coloring`.

- This confirms the earlier manual trace result without applying source by hand:
  the obvious X/Y/Z dirty-temp candidate creates the expected PCode copies, but
  they do not survive into simplify/colorgraph. The remaining mismatch needs a
  different source structure or a deeper lifetime barrier, not this temp shape.

### Remaining issues / new requests

- `--trace-copies` currently reports every newly introduced copy in the whole
  candidate pcdump. For these four dirty-temp candidates that was 50, 50, 50,
  and 57 traces respectively, while the useful signal was only the cursor-copy
  subset. A filtered summary would be much easier to act on, for example:
  "copies involving variables/virtuals touched by the candidate", "copies near
  the candidate's source hunk/basic block", or "copies introduced by this patch
  and not present in the baseline near the patched statement."

- The JSON has the right raw data, but it would help if the human output ranked
  or highlighted the interesting traces: pcode-only/removed-before-coloring
  copies, copies involving the candidate's argument temp, and traces whose
  source/destination virtuals are mentioned by `suggest-coalesce-source`.

## Follow-up after `ef6640f35`

Context: merged `ef6640f35` (`mwcc-debug: filter inline copy trace summaries`)
into `wip/mn-heartbeat` and reran
`suggest-inlines --verify --trace-copies` against `fn_80247510`.

### Improvements that helped

- The human output is much more usable now. It reports compact per-candidate
  trace summaries like `showing 12/57 candidate-relevant traces (45 omitted)`
  instead of dumping every raw candidate-only copy.

- For the grouped X/Y/Z dirty-temp candidate, the highlighted traces include
  the actual cursor copies:
  `r110 <- r50` at block 245,
  `r109 <- r50` at block 262, and
  `r108 <- r50` at block 279. All three are still reported as
  `copy-eliminated-before-coloring`, confirming the no-gain source-shape
  result in a readable way.

- JSON now includes both raw data and summary fields:
  `copy_trace_highlights`, `copy_trace_total_count`, and
  `copy_trace_omitted_count`. That makes it possible to script a concise view
  while keeping the full trace list available.

### Remaining issues / new requests

- The single-axis dirty-temp candidates still highlight unrelated dominant
  source copies (`r135 <- r45`, `r139 <- r45`) while omitting the relevant
  cursor copy (`r108 <- r50`) from `copy_trace_highlights`. For source-shape
  candidates, traces involving the argument temp's source virtual or the
  patched statement's block should outrank generic dominant-source copies.

- Some highlight labels are confusing: the grouped candidate shows entries with
  `interest_reasons: ["removed-before-coloring"]` even when
  `likely_cause`/`transform_category` say `copy-survived`. It would be clearer
  if the reason distinguished "the visible `mr` disappears after register
  coloring / scheduling" from "the copy was eliminated before coloring and the
  destination never reached simplify/colorgraph."

## Follow-up after `cc373568a`

Context: merged `cc373568a` (`mwcc-debug: prioritize source-shape copy traces`)
into `wip/mn-heartbeat` and reran
`suggest-inlines --verify --trace-copies` against `fn_80247510`.

### Improvements that helped

- The source-shape trace prioritization now surfaces the important single-axis
  cursor-copy result. The X/Y/Z single-axis candidates each include the
  relevant `r50 -> r108` trace in `copy_trace_highlights`, with blocks 245,
  262, and 279 respectively depending on which setter was patched.

- The grouped candidate still highlights the full expected cursor-copy set:
  `r50 -> r110` at block 245,
  `r50 -> r109` at block 262, and
  `r50 -> r108` at block 279. All three remain
  `copy-eliminated-before-coloring`, so this is still a strong negative result
  for the dirty-temp source shape.

- The previous ambiguous `removed-before-coloring` label was split into
  `removed-before-coloring` versus `copy-disappears-after-coloring`, which is
  clearer when a copy survives coloring but disappears later in scheduling or
  rewriting.

### Remaining issue / request

- The useful `r50 -> r108` trace is present now, but it still appears after
  several generic `copy-disappears-after-coloring` entries in the single-axis
  candidates. For source-shape candidates, traces involving the touched
  argument/source virtual (`r50` here) should probably sort ahead of generic
  post-coloring-disappear traces, even if both are "interesting."

## Follow-up after `686086dc0`

Context: merged `686086dc0` (`mwcc-debug: rank eliminated inline copies first`)
into `wip/mn-heartbeat` and reran
`suggest-inlines --verify --trace-copies` against `fn_80247510`.

### Improvements that helped

- The ranking fix addresses the remaining issue from `cc373568a`. The
  single-axis dirty-temp candidates now put the relevant `r50 -> r108`
  `copy-eliminated-before-coloring` trace first in `copy_trace_highlights`.

- The grouped candidate now starts with the three expected cursor-copy traces:
  `r50 -> r108` at block 279,
  `r50 -> r109` at block 262, and
  `r50 -> r110` at block 245. This makes the negative result immediately
  readable without scripting around the JSON.

### Result for `fn_80247510`

- This improved diagnostics quality, but did not change the matching result.
  All four dirty-temp inline/source-shape candidates still compile cleanly and
  tie the baseline at `97.14597%`.

- The important copies are still eliminated before coloring, so this remains
  evidence against the current dirty-temp hidden-inline shape being sufficient
  to solve the register/lifetime issue.

### New requests

- None from this run. The previously reported trace-prioritization issue looks
  resolved.

## Manual follow-up after checked-setter probes

Context: tried several local inline shapes for `fn_80247510` after the
dirty-temp candidates proved that the `r50 -> r108/r109/r110` copies are
created but eliminated before coloring.

### Source-shape evidence

- A local checked `HSD_JObjSetTranslateX/Y/Z` wrapper with
  `HSD_JObj* temp = jobj`, standard named asserts, store/checks on `jobj`, and
  `HSD_JObjSetMtxDirtySub(temp)` still produced the expected block-245
  `r110 <- r50` copy, but `trace-copy` reported the same result:
  `copy-eliminated-before-coloring`, first absent at `AFTER REGISTER COLORING`.

- Splitting the dirty check into a two-argument helper made the probe worse:
  the stack frame grew to `-304`, and the function still mismatched. Calling
  `HSD_JObjSetMtxDirty(temp)` directly also grew the frame and did not preserve
  the copy.

- Naming the row jobjs and translation value temporaries in
  `mnVibration_SetCursorPosition` did not help. It still mismatched and removed
  the candidate `r50` copy around block 245 entirely.

- `match-iter-first` suggested `--force-iter-first 151,48,45,153`, but the full
  forced run and several smaller subsets (`48`, `45`, `153`, `151`,
  `48,45`, `48,153`, `45,153`, `151,48`) all still mismatched. This looks like
  a poor fit for the missing-copy problem rather than an iter-order-only
  blocker.

### Tooling feedback

- `match-iter-first --auto-verify` gave no progress output while running and
  had to be killed manually after hanging long enough to be unproductive. It
  would be safer if auto-verify reused the local watchdog by default, surfaced
  the exact force list being tested before compiling, and printed periodic
  phase/status output.

- Verifying `--force-iter-first` is awkward in this multi-function TU because
  `pcdump-local --force-iter-first` is global and has no function-scoped
  variant. The command itself warns about this, but for workflows like
  `fn_80247510` a `--force-iter-first-fn` scope would make ambiguous
  suggestions much safer to test.

## Follow-up after `2242eb84f`

Context: merged `2242eb84f` (`mwcc-debug: scope iter-first auto verification`)
and retried the `match-iter-first` path for `fn_80247510`.

### Improvements that helped

- `pcdump-local --force-iter-first-fn fn_80247510` is now available and works
  as the scoped verification path requested above. A direct scoped run with
  `--force-iter-first 151,48,45,153 --force-iter-first-fn fn_80247510 --diff`
  completed cleanly without affecting the whole TU, though it still
  mismatched. This confirms the iter-first candidate is not enough to solve the
  missing-copy issue.

- `match-iter-first --auto-verify` now prints useful phase output:
  resolving baseline match percent, showing the local watchdog setting,
  printing the exact scoped force list under test, then reading the post-verify
  match percent. That addresses the previous "silent for too long" problem for
  the expensive portion of the command.

### Remaining issue / request

- The auto-verify command still hung after printing `restoring clean report`.
  The live child was `ninja build/GALE01/src/melee/mn/mnvibration.o
  build/GALE01/report.json`; it had to be killed manually. The restore phase
  needs the same timeout/progress treatment as the forced compile phase, and
  ideally should report whether it is restoring source, object, report, or
  cache state.

## Follow-up after `2866b508e`

Context: merged `2866b508e` (`mwcc-debug: bound iter-first restore phase`) and
retried `match-iter-first --auto-verify` for `fn_80247510`.

### Improvements that helped

- The restore phase now reports clear status:
  `restoring object/report: ninja build/GALE01/src/melee/mn/mnvibration.o build/GALE01/report.json`.
  It also prints periodic progress lines, so the command is no longer silent
  while cleanup is running.

- The restore phase is now bounded. In this run it timed out cleanly at the
  default 180 seconds and reported `restore object/report: exit 124`, instead
  of requiring a manual kill.

### Remaining issues / requests

- `MWCC_DEBUG_HANG_TIMEOUT=8` does not affect the restore phase; restore uses
  `MWCC_DEBUG_RESTORE_TIMEOUT` and defaults to 180 seconds. That is documented
  in the skill now, but it was easy to miss during iteration. It would be useful
  if `match-iter-first --auto-verify` printed the active restore timeout up
  front, or inherited the shorter hang timeout when no restore-specific timeout
  is set.

- The command process still exited successfully even though the restore phase
  timed out and reported exit 124 internally. If object/report restoration
  fails, scripted workflows need a non-zero exit status or a machine-readable
  top-level status so they do not treat the run as fully cleaned up.

- The restore stderr tail showed repeated
  `ninja: warning: premature end of file; recovering`. If this is a known
  partial-report or interrupted-ninja state, the tool should surface the likely
  cleanup action.

### Result for `fn_80247510`

- The scoped iter-first candidate still tied baseline:
  `97.15% -> 97.15% (+0.00%)` for
  `--force-iter-first 151,48,45,153 --force-iter-first-fn fn_80247510`.
  This remains a negative result for the iter-order-only path.

## Manual follow-up after inline dirty-helper probes

Context: after the scoped iter-first path tied baseline, tried two narrower
inline variations around the cursor `HSD_JObjSetTranslate*` expansion.

### Source-shape evidence

- A one-argument split dirty helper, modeled after the matched `ifstatus.c`
  style, was structurally wrong here. It compiled into actual
  `bl HSD_JObjMtxIsDirty` calls instead of the inline dirty-test body, shortened
  the cursor-position block, and still mismatched.

- A fully expanded local dirty-test helper avoided the `HSD_JObjMtxIsDirty`
  calls and produced a dirty-check body closer to the target, including
  explicit assert/flag-test logic before `HSD_JObjSetMtxDirtySub`. It was still
  a regression: the frame grew from `-280` to `-304`, callee-save assignments
  cascaded broadly, and `fn_80247510` still mismatched.

- Net result: the missing cursor-pointer copies are not solved by simply
  splitting the dirty helper or manually expanding the dirty test. The source
  shape still needs a lifetime barrier that preserves a short-lived dirty
  pointer without increasing the frame or moving the long-lived cursor pointer.

### Tooling feedback

- `pcdump-local` crashed with a raw `FileNotFoundError` traceback when
  `build.ninja` was absent. Running `python configure.py` fixed the local build
  metadata, but `pcdump-local` should probably catch this and print an
  actionable diagnostic like "build.ninja missing; run python configure.py"
  instead of a full Python traceback.
