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

## Follow-up after `bcef18570`

Context: merged `bcef18570` (`mwcc-debug: report iter-first cleanup failures`)
and reran `match-iter-first --auto-verify` for `fn_80247510`.

### Improvements that helped

- The restore timeout now falls back to `MWCC_DEBUG_HANG_TIMEOUT` as requested.
  With `MWCC_DEBUG_HANG_TIMEOUT=8`, auto-verify printed
  `restore timeout: 8s (MWCC_DEBUG_HANG_TIMEOUT)` and timed out cleanup after
  eight seconds instead of waiting the previous 180-second default.

- A failed restore now propagates to the top-level process status. The command
  exited with status `124` after the restore timeout, while still printing the
  iter-first result. That makes the failure script-detectable.

- The cleanup hint is useful and specific. For the repeated
  `ninja: warning: premature end of file; recovering` case it suggested
  `ninja -t recompact` and, if needed, rebuilding metadata.

### Remaining issues / requests

- The `match-iter-first --help` text still only describes scoring the forced
  iter-first list. It does not mention restore cleanup, timeout env vars,
  `cleanup_complete=false`, or non-zero exit behavior. The skill doc has the
  details, but the CLI help is where I looked first during iteration.

- After running the suggested `ninja -t recompact`, manually retrying
  `ninja build/GALE01/src/melee/mn/mnvibration.o build/GALE01/report.json`
  expanded into a large rebuild (`[1/969]...`) and hit my 30-second guard. For
  this workflow, a safer cleanup command would avoid kicking off a full rebuild
  when the goal is only to restore the one touched object/report state, or would
  print that the next cleanup step may be expensive.

- The guarded manual restore retry left its `wibo ... mnvibration.c` child
  orphaned under PID 1 in `UE` state after timeout; `kill -9` did not clear it.
  That was outside `match-iter-first` itself, but it makes the cleanup hint
  risky to run manually. A debugger-provided cleanup/restore command that owns
  the process tree would be safer than asking the caller to rerun raw `ninja`.

### Result for `fn_80247510`

- The iter-first candidate remains a no-gain proof:
  `97.15% -> 97.15% (+0.00%)` for
  `--force-iter-first 151,48,45,153 --force-iter-first-fn fn_80247510`.

## Follow-up after `56b9dd5e3`

Context: merged `56b9dd5e3` (`mwcc-debug: guard iter-first restore cleanup`)
and retried `match-iter-first --auto-verify` plus several source-shape probes
for `fn_80247510`.

### Improvements that helped

- `match-iter-first --help` now documents the auto-verify cleanup behavior,
  the managed restore phase, `MWCC_DEBUG_RESTORE_TIMEOUT`, fallback to
  `MWCC_DEBUG_HANG_TIMEOUT`, and `cleanup_complete=false`/non-zero failures.
  This addresses the prior discoverability gap.

- Auto-verify now uses the scoped force list and managed restore path. The run
  printed:
  `--force-iter-first 151,48,45,153 --force-iter-first-fn fn_80247510`, then
  refused to launch a 575-step restore because it exceeded
  `MWCC_DEBUG_RESTORE_MAX_STEPS=64`. That is a much safer failure mode than
  the earlier raw `ninja` cleanup path that could launch a large rebuild and
  leave orphaned `wibo` children.

- `suggest-inlines --seed-source coalesce --json --emit-hunks` now emits the
  grouped X/Y/Z hidden dirty-argument temp candidate directly. This is the
  right diagnostic family for the current cursor-copy mismatch, even though the
  candidate still does not match.

### Remaining issues / requests

- After managed restore refuses an oversized dry-run plan, the worktree remains
  in a stale-report state (`worktree-doctor` still reports
  `build/GALE01/report.json is older than build.ninja`). The refusal is correct,
  but the next safe step is not obvious. A diagnostic explaining why the dry-run
  expanded to 575 steps, or a narrower "repair only report/object metadata if
  possible" mode, would help avoid falling back to raw `ninja`.

- `pcdump-local --diff` without `-f` defaulted to the first function in the TU
  (`mnVibration_JObjGetTranslationX`) and failed because that inline helper is
  not in `report.json`. The help text explains `-f`, so this is mostly user
  error, but the failure could suggest `--function` when the chosen symbol is
  static inline or absent from the report.

### Source-shape evidence

- The scoped iter-first candidate still ties baseline:
  `97.15% -> 97.15% (+0.00%)`.

- The grouped translate-argument temp candidate regressed the frame from `-280`
  to `-288` and changed the cursor register itself rather than introducing the
  target short-lived dirty pointer copy.

- Hand-written dirty-call helper functions emitted real helper calls and
  shortened the cursor block badly. Macro-expanded dirty-temp variants stayed
  inline but still coalesced the cursor and dirty pointer into a single
  register; adding a stable cursor local restored the `-280` frame but dropped
  the target `f30` save and still mismatched. These probes were reverted.

## Attempt-history visibility gap

Context: before trying another `fn_80247510` inline/source-shape probe, I
refreshed the function's attempt history to avoid repeating prior experiments.

- `melee-agent attempts show fn_80247510` displayed only attempts `#42-#61`
  and did not make the truncation obvious. The raw ledger had all 61 attempts,
  so I had to query `/Users/mike/.config/decomp-me/attempt_ledger.json`
  directly with `jq` to reconstruct the complete experiment map.

- This matters for the `mwcc-debug` workflow because source-shape experiments
  are often guided by old pcdump clues. If the visible attempt list omits older
  dead ends like value temps, row locals, or dirty-pointer aliases, agents are
  likely to repeat expensive/known-bad variants after context compaction.

- Suggested fix: add an explicit truncation banner to `attempts show`, plus an
  `--all` or `--limit` option. A compact one-line mode like
  `#N [match outcome classification] retained=... blocker=... :: note` would
  also be useful for debugger-guided sessions.

## Follow-up value-temp probe result

Context: after reviewing the full history, I tried to isolate the one useful
clue from earlier broad value-temp experiments without recreating their large
frame/register cascade.

- Tight `f32` value temps inside `mnVibration_SetCursorPosition` are not a
  viable source shape for `fn_80247510`. X-only, Y-only, and `register f32`
  X-only variants all expanded the frame from `-280` to `-288`.

- `mwcc-debug diff` showed temp/stack virtual churn, but final scheduled code
  still passed the cursor directly to each hidden dirty call (`mr r3,r31`).
  None of these variants produced the target short-lived aliases
  (`mr r30,r31` / `mr r28,r31`) before `HSD_JObjSetMtxDirtySub`.

## Port-panel ordering probe

Context: pivoted from the cursor-copy mismatch to the smaller port-panel block
in `fn_80247510`, where the target wants the byte-to-float state store and
`mnVibration_804D4FE8` halfword load before loading `mnVibration_804D6C28`.

### Useful signals

- `pcdump-local` plus `debug analyze` made the blocker clear: in the retained
  `u8 state_copy` shape, the state byte virtual (`r133` / `r131`) interferes
  with the global-load virtual (`r216` / `r239`) because the `lwz
  mnVibration_804D6C28` is present before the state conversion store in the
  colored block. That forces `state=r5, global=r4`; the target needs
  `state=r4, global=r5`.

- `--force-phys-fn fn_80247510 --force-phys "133:4,216:5,217:4,131:4,239:5,240:4"`
  was a useful proof: forced registers changed the local block to
  `lbz r4` / `lwz r5`, but the instruction order still stayed wrong
  (`lwz mnVibration_804D6C28` before `lhzx` and before the state store). This
  confirms the remaining port-panel issue is source/PCode ordering, not just
  allocator choice.

### Remaining issue / request

- The checked-in `mwcc-debug` skill documents `--force-phys "36:31"` but does
  not mention that multi-function TUs require `--force-phys-fn <function>`.
  It also does not explain the distinction between `--force-phys` and
  `--force-phys-iter` when class-specific forcing is desired. The tool's
  runtime warning explained this, but having the example in the skill would
  make forced-register proofs faster and less error-prone.

## Port-panel controlled source experiments

Context: after the force-phys proof showed the remaining port-panel mismatch is
source/PCode order, I tested new source shapes that operate outside the already
exhausted helper-local/index-local space.

### Experiment results

- Passing an explicit `u8* port_state` to the setter, without otherwise changing
  loop lifetime, compiled exactly like the retained `u8 state_copy` baseline:
  `97.159615%`, opcode `0.98219178`, line delta `6`, hunk count `27`.

- Making `port_state` a loop-scope pointer used by both branch tests and setter
  calls regressed to `96.0%`, opcode `0.97668038`, line delta `8`, hunk count
  `36`. It kept the pointer too long, moved the local block to `r31`, and still
  loaded `mnVibration_804D6C28` before `lhzx` / the state store.

- Splitting state update and panel animation into two phases, with the branch
  doing `data->x0[...] = state` and passing `data->x0[...]` to an animation
  helper, compiled exactly like baseline.

- Adding an explicit branch-local `u8 state_copy` before the animation helper
  also compiled exactly like baseline.

- A macro-shaped setter boundary regressed to `97.11869%`, line delta `6`, hunk
  count `31`. It kept the same bad `lwz mnVibration_804D6C28` ordering and
  changed the panel JObj register family away from the target.

- Rewriting the surrounding branch as first-check plus `continue`, then a
  separate second check, compiled exactly like baseline.

- Hoisting the current port state byte before both button checks regressed to
  `95.57435%`, opcode `0.97597804`, line delta `9`, hunk count `31`. It created
  another long-lived byte value and still did not delay the global load.

### Tooling requests

- Add an order-trace mode for one function/window that reports the relative
  order of tagged instructions across MWCC passes. For this block, I want to
  tag `stb state`, `lbz state`, `lhzx mnVibration_804D4FE8`, `stw state`, and
  `lwz mnVibration_804D6C28`, then see the first pass where the global load is
  before the table/state work.

- Add a scheduler/dependency explanation for a selected window: list dependency
  edges and ready-list decisions for why `lwz mnVibration_804D6C28` is allowed
  and chosen before `lhzx` / `stw state`. If the order is already present before
  scheduling, say which earlier pass/source PCode introduced it.

- Add a local-window scorer for repeated experiments. Whole-function fuzzy
  scores are useful, but for this blocker I need a compact report for the
  `+344..+378` and `+3d4..+408` windows: opcode order, register class, stack
  slots, and whether the global load is before or after table/state work.

## Cursor reference comparison after reorientation

Context: after exhausting same-pointer dirty aliases and port-panel ordering
variants, I compared other menu cursor code to `fn_80247510` to check whether
the vibration cursor block might be trying to follow a shared/canonical helper
shape.

### Useful signals

- `mnStageSw_80236178` is a 100% matched function with the same natural idiom:
  load a cursor JObj, compute a Y delta from two reference JObjs, then call
  `HSD_JObjSetTranslateX/Y`. Its final asm passes the cursor directly to the
  hidden dirty calls (`mr r3,r31`), and `debug trace-copy
  build/mwcc_debug/mnstagesw_cursor_compare.txt -f mnStageSw_80236178
  --list-copies --near-block 20` reports zero copies.

- `mnGallery_802591BC` is also matched and has the simpler cursor-copy idiom
  (`SetTranslateX/Y/Z(jobj, GetTranslation*(child))`). Its final asm likewise
  uses the destination JObj directly for hidden dirty calls, with no short-lived
  cursor alias.

- This makes it unlikely that `fn_80247510`'s target-only `mr r30,r31` /
  `mr r28,r31` copies are the normal result of a shared menu cursor helper or
  the stock `HSD_JObjSetTranslate*` inline. The vibration target still appears
  to need a source shape that creates a semantically live dirty-call alias before
  register coloring, not just the canonical cursor-position source.

### Experiment results

- A custom dirty-argument cursor setter did create an early PCode copy
  (`r115 <- r49`), but `trace-copy` classified the destination as pcode-only
  and the copy disappeared before/at register coloring. The source shape
  cascaded the surrounding registers and was reverted.

- A two-parameter cursor setter called with a separate dirty-pointer expression
  (`data->cursor_gobj->hsd_obj`) compiled identically to baseline:
  `97.159615%`, opcode `0.9821917808219178`, line delta `6`, hunk count `27`.
  There were no relevant copies near the cursor block, so this also was
  reverted.

### Tooling requests

- `debug mutate insert-alias -f fn_80247510 --var jobj --at 0 --name
  cursor_alias` hung for more than 50 seconds before printing any candidates.
  It would be much more useful if this command first printed a quick list of
  possible insertion/read locations, or accepted a timeout/progress mode that
  fails with partial candidate information instead of producing no output.

- `trace-copy` is good enough to show that a candidate alias is pcode-only and
  absent after coloring, but for this blocker the key missing explanation is
  narrower: which pass eliminated the pcode-only alias, whether it ever entered
  simplifygraph/colorgraph, and what source property would make the destination
  become an allocator-visible virtual instead of a disposable copy.

## Expert-suggested cursor and port-panel probes

Context: after sharing the 69-attempt history with another matching expert, I
tested the highest-signal new hypotheses against the current `97.159615%`
baseline.

### Cursor dirty-alias probes

- Distinct expression paths (`cursor_jobj` from `data->cursor_gobj->hsd_obj`,
  dirty target from `mnVibration_804D6C28->user_data->cursor_gobj->hsd_obj`)
  regressed to `95.60846%`, opcode `0.9084699453551912`, line delta `2`, hunk
  count `75`. It produced a genuinely distinct dirty register, but not the
  target `mr r30,r31` / `mr r28,r31` saves; it cascaded the surrounding
  cursor/data registers instead.

- `HSD_JObjSetMtxDirtyInline(jobj)` inside local cursor setters regressed to
  `88.428375%`, opcode `0.66`, line delta `78`, hunk count `28`. The inline
  function path emitted direct dirty calls (`mr r3,r31`) and did not create the
  target saves.

- Single-use dirty temp (`dirty_jobj = jobj`, use `dirty_jobj` only as the
  `HSD_JObjSetMtxDirtySub` argument, all checks still use `jobj`) regressed to
  `96.5116%`, opcode `0.9821917808219178`, line delta `6`, hunk count `60`.
  It kept dirty calls in `r30` (`mr r3,r30`), but still did not emit the target
  local copies from `r31` into newly dead registers.

- Hybrid `nav_data->cursor_gobj->hsd_obj` dirty pointer regressed to
  `96.27013%`, opcode `0.9084699453551912`, line delta `2`, hunk count `51`.
  Like the global distinct-expression probe, it used/reloaded a distinct dirty
  value rather than producing the target copy from the live cursor register.

### Port-panel volatile probe

- Volatile state-byte reload (`state_copy = *(volatile u8*) &data->x0[port+2]`)
  regressed to `96.7367%`, opcode `0.9753761969904241`, line delta `4`, hunk
  count `24`. It changed the local state read into an `add` plus `lbz 2(r3)`
  shape and still left the `mnVibration_804D6C28` global load before the table
  halfword load/state store.

### Permuter setup finding

- `debug gen-permuter-config -f fn_80247510 --pattern alias-split --force`
  generated a more appropriate config than the auto-detected low-severity
  `widen-u8-to-u32` profile.

- The existing `/Users/mike/code/decomp-permuter/nonmatchings/fn_80247510`
  import is stale: its `base.c` predates the current hidden cursor-position
  helper/source state, and `debug verify-perm .../base.c -f fn_80247510` fails
  to transfer/compile in the real tree. A serious C1 run needs a fresh import
  from the current source or a tool command that refreshes the permuter
  nonmatching in place.

### Tooling requests

- `gen-permuter-config` can write a useful settings file even when the
  corresponding permuter `base.c` is stale/non-transferable. It would help if
  the command optionally verified the base candidate against the real tree and
  warned "settings generated, but this permuter import is stale" before an
  agent spends time on a run that cannot be triaged cleanly.

- A one-command "refresh permuter import from current source/function" wrapper
  would make the C1 recommendation much easier to execute safely. The manual
  `decomp-permuter/import.py` path is easy to misuse in this repo because the
  build is ninja/configure-based and the old import may silently lag behind the
  current retained source shape.

## Targeted permuter run on cursor blocks

Context: after the dirty-alias source probes failed, I tried the C1
decomp-permuter recommendation against a fresh import from the current source.

### Setup and run results

- A fresh `decomp-permuter/import.py --function fn_80247510` import from the
  current `src/melee/mn/mnvibration.c` compiled standalone, but
  `debug verify-perm nonmatchings/fn_80247510/base.c -f fn_80247510` initially
  failed to transfer. The pruned `base.c` had a duplicate
  `mnVibration_802474C4` prototype wrapped in `#pragma push` /
  `#pragma dont_inline on` / `#pragma pop`, so the verifier extracted a stray
  `#pragma pop` with `fn_80247510`. Removing that generated pragma/prototype
  block made the base transfer cleanly at the current `97.159615%` baseline.

- I generated the alias-split profile and wrapped only the up-nav/down-nav
  cursor blocks in `PERM_RANDOMIZE(...)` to keep the search focused on the six
  missing cursor dirty-call copies.

- A quick stock run and a short mwcc-blended run produced only score-11175 tied
  candidates. `debug triage-perm` found no improvement: most transferred as
  exact baseline, two regressed slightly (`97.12551%` / `97.13915%`), and one
  build-failed on real-tree transfer.

- The full high-parallel stock run used `-j 10 --better-only` and stopped at
  exactly 60,000 iterations. Throughput was about 35 iterations/second. The
  minimum score seen was still `11175`; there were no candidates below the
  current baseline score, so no new output directories were produced.

### Tooling requests

- `debug permute --perm-root` currently acts like it is both the decomp-permuter
  code root and the nonmatching data root. That made a repo-local fresh import
  awkward: pointing `--perm-root` at the repo let it find
  `nonmatchings/fn_80247510` but then `permute_with_mwcc.py` could not import
  decomp-permuter's `src.compiler`. I worked around this by invoking
  `permute_with_mwcc.py` manually with `MELEE_PERMUTER_ROOT` and `MELEE_ROOT`.
  Splitting these into separate options, or letting `debug permute` accept an
  explicit perm-dir path, would make fresh-import workflows much safer.

- `triage-perm` reports `status: build-failed` with `first_diag: null` for at
  least one candidate. A short captured compiler/ninja diagnostic would make it
  easier to distinguish harmless transfer artifacts from potentially useful
  near-miss candidates.

- A wrapper-level `--max-iterations` option for `debug permute` would be useful.
  For this run I had to write an external monitor that parsed progress text and
  stopped the process at 60,000 iterations.

## `mwcc-inspect` wrapper hang on `mnvibration.c`

Context: I tried the lighter-weight front-end inspector on
`src/melee/mn/mnvibration.c` to compare `fn_80247510` with the matched
`fn_80248A78` cursor setup.

### Result

- `tools/workflow/mwcc-inspect.sh src/melee/mn/mnvibration.c` hung silently:
  the local wrapper processes stayed alive, `build/mwcc_inspect/mnvibration.txt`
  remained zero bytes, and I did not see a remote `MwccInspectorCLI.exe` or
  `mwcceppc.exe` process. I killed the local wrapper after confirming it was
  stuck.

- A direct SSH invocation using the same local `ninja -t commands` compile
  arguments succeeded and produced a 348 KiB
  `build/mwcc_inspect/mnvibration.txt` dump with no stderr.

- The successful dump was useful: in `fn_80247510`, all six dirty calls are
  front-end `HSD_JObjSetMtxDirtySub([jobj])` with no separate temp object. In
  matched `fn_80248A78`, the local cursor setters have explicit compiler temps
  such as `[@734] = [cursor_jobj]` followed by `ftCo_800C6AFC([@734])`.

### Tooling requests

- The wrapper should print phase markers or a `--verbose` trace around fetch,
  checkout, command construction, SSH start, and remote inspector launch. A
  silent local hang with an empty output file is hard to distinguish from a
  slow inspector run.

- Add a wrapper timeout or heartbeat for the remote launch phase. If no output
  file bytes appear and no remote inspector/compiler process exists after some
  interval, fail with the SSH command and resolved remote ref instead of
  waiting indefinitely.
