# mwcc-debug ↔ decomp-permuter integration

Implementation notes for the Tier 7e integration. Captures what v1
ships, where the friction points are, and what v2/v3 would look like.

## v1 (shipped)

Two complementary commands cover the matching agent's MVP request from
the session findings doc:

### `melee-agent debug verify-perm <candidate.c> -f FN [--keep]`

Apply ONE permuter candidate to the real source tree and report
whether match% actually improves. Removes the "permuter score=1320 but
actual checkdiff shows no change" cycle by always recompiling against
the real (non-preprocessed) source.

### `melee-agent debug triage-perm <perm-dir> -f FN [--apply-best] [--top N]`

Batch version. Iterates every `output-NNNN-N/source.c` in a permuter
session output, applies each to the real tree, builds, reads match%
from `report.json`, and produces a ranked list of which candidates
actually improve real-tree match%.

Per-candidate cost: ~5-10 seconds (one ninja per .c + report.json
regen). For a typical permuter session with ~100 winners, total triage
time is a few minutes.

## How to use with decomp-permuter

Upstream decomp-permuter doesn't have a `--scorer` flag at the moment.
The integration is post-hoc:

```bash
# Run permuter as normal — let it find winners against objdiff bytes
./permuter.py path/to/permute_dir --threads 8

# Permuter writes winning candidates to nonmatchings/* (or similar).
# Triage them against the real tree:
melee-agent debug triage-perm permute_dir/nonmatchings -f my_stuck_fn

# If a winner transfers, apply it:
melee-agent debug triage-perm permute_dir/nonmatchings -f my_stuck_fn \
    --apply-best
```

The triage step is what catches the base.c-vs-real-tree drift the
agent's session noted.

## Why per-iteration integration is deferred

The natural v2 — pluging `melee-agent debug score` into a permuter
`--scorer` flag for per-candidate IGNode-distance scoring — requires
either:

1. A pcdump per candidate. Each pcdump is ~30 seconds (SSH to
   nzxt-local, run mwcceppc with debug DLL, stream output back). At
   1000+ permuter candidates per session, that's 8+ hours of pcdumps.
2. A local IGNode estimator built from objdump output instead of
   pcdump. Possible but loses some of what pcdump provides (e.g.
   SIMPLIFY GRAPH events, COLORGRAPH DECISIONS per-iter data).

For now, v1 (post-hoc triage) gets ~90% of the value at ~1% of the
cost. v2 makes sense once the project is consistently running 1000+
iteration permuter sessions on the few remaining stuck functions.

## v2 design sketch (when warranted)

If/when v2 is needed:

1. **Local mwcc invocation.** Build a path-of-least-resistance way to
   run mwcceppc locally with debug DLL output (e.g., wibo +
   rosetta) — the current SSH workflow is too slow for the inner loop.
2. **Custom scorer wrapper.** A shell/Python wrapper that takes a .o
   path (what permuter's `--scorer` would pass), generates the pcdump
   for that .o, and runs `debug score`. Wraps the SSH or local
   invocation transparently.
3. **decomp-permuter patch.** Add `--scorer-command <cmd>` to the
   permuter CLI that invokes the wrapper instead of the default
   objdiff-bytes scorer.
4. **Score weight tuning.** Likely needs the IGNode-distance to be the
   PRIMARY signal (high weight) and bytes a SECONDARY signal (low
   weight). Current default weights are byte-primary, which is the
   right starting point.

## v3 design sketch (research-grade)

A truly "guided" permuter that knows about MWCC's pipeline:

- Mutation engine biased by analyze output: if the wrong virtual is
  r36 with target r31, prefer mutations that change r36's live range
  or its IG-neighbors' lifetimes
- Decl-order enumeration as a first-class mutation strategy (overlaps
  with our `enumerate-decl-orders` command)
- Pattern catalog awareness — when permuter sees a stuck virtual with
  no direct blocker, prefer the decl-order mutation family

This is well beyond MVP scope and would best live in a separate tool
rather than as a permuter patch.

## Files in this repo

- `tools/melee-agent/src/cli/debug.py` — `verify-perm`, `triage-perm`,
  `score`, `derive-target`, `guide` commands
- `tools/melee-agent/src/mwcc_debug/scoring.py` — score function +
  ScoreWeights + derive_target_from_function
- `tools/melee-agent/src/mwcc_debug/source_patch.py` — function-body
  extraction/replacement (used by verify-perm and triage-perm)

## Files NOT in this repo (potential v2)

- A vendored or forked `decomp-permuter` with the `--scorer-command`
  hook. Currently you'd patch it manually if you wanted to try v2.
