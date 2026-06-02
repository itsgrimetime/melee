# mndiagram3 cascade wins — handoff for PR prep

**Branch:** `wip/mndiagram3-cascade-wins`
**Worktree:** `/Users/mike/code/melee-mndiagram3-wins`
**Source session:** May 20, 2026 in worktree `youthful-lichterman-2f2c7a`
**Source branch (snapshot):** `decomp/mndiagram3` @ `670f55d73` (pre-PR #2535)

## What landed here

Commit `48628ba57`: `mnDiagram3_8024714C` 86.6% → **93.3%** (+6.7%) — single-line change to pass `row_spacing` as 6th arg to `HSD_SisLib_803A5ACC` instead of `mnDiagram3_804DBFFC` duplicated. Matches the expected `fmr f4, f30` codegen.

## Wins that *didn't* apply to master cleanly

The source session (`decomp/mndiagram3`) achieved much higher match% than master on the same functions:

| Function | Master | Source branch | Δ |
|---|---|---|---|
| mnDiagram3_8024714C | 86.6% / 72.7% opcode | **99.4% / 100% opcode** | +12.8% |
| fn_802461BC | 85.3% / 57.1% opcode | **97.4% / 96.3% opcode** | +12.1% |
| mnDiagram3_80245BA4 | 90.6% / 88.9% opcode | 97.5% / 68.9% opcode | +6.9% match, -20% opcode |

The source branch's gains came from a pre-PR-#2535 code structure that the upstream PR has since refactored. Direct cherry-picking failed because the file shape changed dramatically. Wins that *partially* applied:

- **`int scroll` + `(u8) scroll` cast at use site** — on master gives match -1.1% but opcode similarity +11.1% (structural improvement, mixed bytes). The `checkdiff` classifier flags this as "progress toward true match" but it regresses the shippable score.
- **`val = (u8) i; ... val += (u8) scroll` split** — on master gives small regression (-0.3% / -0.2%). The pattern relied on a different `limit` placement than master uses.
- **PAD_STACK(64) → PAD_STACK(72)** — no change on master (different surrounding locals).
- **Limit-before-val reorder** — regression -0.3% / +8.8% opcode (structural improvement, byte regression).

## What's in the snapshot worktree

Full contents of `decomp/mndiagram3` (with all in-session commits) is still in the source worktree at `/Users/mike/code/melee/.claude/worktrees/youthful-lichterman-2f2c7a` (branch `decomp/mndiagram3`). The full `src/melee/mn/mndiagram3.c` from there is at 99.4% / 100% opcode for `mnDiagram3_8024714C`. If a PR prep wants to do a full structural rebase rather than minimal deltas, that worktree has the reference shape.

## Suggested follow-up

1. Ship the +6.7% delta as-is in a small standalone PR (it's a clean one-liner with the right semantic argument).
2. For larger gains, the source branch's *opcode* sequence on `mnDiagram3_8024714C` is byte-perfect with target — just register cascade differences. A targeted re-rebase that picks up the val += pattern and int scroll + cast on a re-shaped master function would likely close another 5-10% match%.
3. The decomp/mndiagram3 worktree at youthful-lichterman-2f2c7a has the full session history if anyone wants to revisit individual experiments.

## Session diagnostic context

- mwcc-debug verdict: probable ceiling (param-iter-ceiling pattern, structural)
- Permuter ran 200K+ iterations on the 99.4% baseline, best score 130 vs baseline 140 (cruft only, e.g. `val -= (val = (u8) limit)`)
- Force-coalesce / force-iter-first tried — all worse or crash (overlapping virtuals)
