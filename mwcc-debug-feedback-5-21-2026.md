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
