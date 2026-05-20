# mwcc-debug ↔ decomp-permuter integration

Implementation notes for the integration. Captures what's shipped,
where the friction points are, and what v2/v3 would look like.

## Important: there is NO patched permuter

`decomp-permuter` itself is unforked upstream. mwcc-debug provides
complementary CLI commands that:
1. **Inform** permuter (pre-run) by generating pattern-tuned config
2. **Filter** permuter output (post-run) by triaging real-tree match%

If a new agent is looking for "the augmented permuter binary," they
won't find one. Direct them at the three commands below.

## Tier 0 (shipped — basic integration)

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

## Tier 1 (shipped — pattern-tuned config)

### `melee-agent debug gen-permuter-config -f FN [options]`

Generates a `<perm_root>/nonmatchings/<fn>/settings.toml` whose
`[weight_overrides]` are tuned to mwcc-debug's pattern detection.
Saves the agent from hand-tuning weights per function.

Pattern → weight-boost mapping (from `patterns.py`):

| Pattern | Boosted mutations | Why |
|---------|-------------------|-----|
| `decl-order` | reorder_decls=80, temp_for_expr=30, ins_block=20 | Direct decl moves + intermediate decls in new positions |
| `alias-split` | temp_for_expr=60, refer_to_var=30, expand_expr=15 | Fresh-local extraction shortens live ranges |
| `widen-u8-to-u32` | randomize_internal_type=50, cast_simple=30 | Type changes for promotion-mask elimination |
| `shrink-s32-to-u8` | randomize_internal_type=50, cast_simple=30 | Mirror of widen |
| `drop-variadic-cast` | cast_simple=60, expand_expr=30 | Remove explicit (f32) casts |
| `subexpr-extract` | temp_for_expr=80, expand_expr=30 | Pull subexpressions into named locals |
| `chained-init` | chain_assignment=50, duplicate_assignment=20 | `a = (b = 0)` style |
| `param-iter-ceiling` | (refuses to generate) | Tier 6 — no C-source fix exists |

Detection: scores against `--target` (a YAML/JSON spec, typically
produced by `debug derive-target`); the highest-severity suggestion's
category determines the pattern. With no target, falls back to stock
settings unless `--pattern` is given.

Special case for `param-iter-ceiling`: the command refuses to generate
a config and instead prints "this is Tier 6 — permuter cannot fix it,
use `match-iter-first` instead." Pass `--force` to override.

For `decl-order`: also prints a recommendation to try
`enumerate-decl-orders` first, which is deterministic and ~100x faster
than letting permuter rediscover decl-order via random mutation.

### Workflow

```bash
# 1. Generate a tuned config
melee-agent debug gen-permuter-config -f my_stuck_fn \
    --target target.json

# 2. Run permuter (unmodified upstream)
cd ~/code/decomp-permuter
./permuter.py nonmatchings/my_stuck_fn --threads 8

# 3. Triage winners against the real tree
cd ~/code/melee
melee-agent debug triage-perm \
    ~/code/decomp-permuter/nonmatchings/my_stuck_fn -f my_stuck_fn

# 4. Apply the best confirmed winner
melee-agent debug triage-perm \
    ~/code/decomp-permuter/nonmatchings/my_stuck_fn -f my_stuck_fn \
    --apply-best
```

## Tier 2 (shipped — per-iteration mwcc-debug scoring)

### `melee-agent debug permute -f FN [--blend α]`

Runs decomp-permuter with a monkey-patched scorer that blends
`melee-agent debug score-source` (IGNode-distance from pcdump) into
objdiff's byte-distance scoring. Per-iteration, the candidate source
is compiled via local `wibo + mwcceppc_debug.exe` and scored against
a derived target.

Final score blend: `bytes + α * mwcc` (default α = 0.1). Byte distance
stays dominant; the mwcc signal breaks ties between byte-equivalent
candidates — most useful for register-cascade ceilings where the byte
scorer can't distinguish many mutations.

Prerequisites (in addition to Tier 0/1):
- `melee-agent debug setup-local` (one-time wibo + DLL + compiler patch)
- `<perm-root>/nonmatchings/<FN>/` exists (run `import.py` first)
- compile.sh fixed for mac (`melee-agent debug fix-perm-compile <perm_dir>`
  — auto-applied by `gen-permuter-config`)

Workflow:

```bash
# 1. Tune permuter weights for the function's detected pattern
#    (also auto-fixes compile.sh for mac+wine)
melee-agent debug gen-permuter-config -f my_stuck_fn

# 2. Run permuter with mwcc-debug blending. Target auto-derived.
melee-agent debug permute -f my_stuck_fn --blend 0.05

# 3. Triage winners against the real tree as usual
melee-agent debug triage-perm \
    ~/code/decomp-permuter/nonmatchings/my_stuck_fn -f my_stuck_fn
```

### Implementation notes

- Built on `tools/melee-agent/scripts/permute_with_mwcc.py`, a thin
  monkey-patch wrapper around upstream `permuter.py`. No fork of
  decomp-permuter needed.
- Single-threaded by default (`-j 1`). Our DLL writes pcdump.txt to
  project root, so parallel threads would race. Per-thread output
  handling deferred.
- The scoring path uses `score-source --cflags-from <unit>` so a
  candidate staged at `nonmatchings/.permuter_score_<pid>.c` gets
  compiled with the original TU's flags — no need to fake a ninja
  build block for the staged file.
- On scoring failure (timeout, parse error, etc.), we fall back to
  the plain objdiff score so permuter never blocks on our infrastructure.

### When NOT to use it

- Pure byte-distance cases (functions where the byte scorer is doing
  fine, like first-pass decomp under 70%). Tier 2's marginal value is
  on the last mile — 95%+ match where byte distance has flatlined.
- Pattern-targeted searches that converge in <100 iterations.
  `enumerate-decl-orders` is still faster for decl-reorder, and Tier 1's
  weight tuning often gets there in a few hundred iterations without
  needing Tier 2.

## Tier 3 (shipped — targeted mutations + multi-start)

Where Tier 2 says "evaluate candidates better," Tier 3 says "generate
better candidates to start with." Given a stuck function, the agent
identifies WHICH variable is blocking via the new symbol bridge, then
applies targeted mutations (type-change, alias-split) directly on that
variable. Each mutation becomes a permuter starting point.

### Primitives (each also a CLI command)

| Command | Purpose |
|---|---|
| `debug var-to-virtual -f FN <var>` | Predict MWCC virtual for a source variable name |
| `debug virtual-to-var -f FN <ig_idx>` | Inverse lookup |
| `debug mutate type-change -f FN --var V --type T` | Change a local's declared type |
| `debug mutate insert-alias -f FN --var V --at N` | Alias before N-th reading statement |
| `debug tier3-search -f FN` | Multi-start orchestrator (plans + materializes seeds) |

### Workflow

```bash
# 1. Identify the blocker
melee-agent debug guide -f my_stuck_fn

# 2. Plan + materialize seeds
melee-agent debug tier3-search -f my_stuck_fn --budget 5

# 3. For each tier3_seed_<i>/ that compiled, run permuter (Tier 2)
for seed in ~/code/decomp-permuter/nonmatchings/my_stuck_fn/tier3_seed_*; do
    melee-agent debug permute -f my_stuck_fn \
        --perm-root ~/code/decomp-permuter \
        --blend 0.05
done
```

### Calibration + confidence

The symbol bridge reports confidence per binding: `best-guess`,
`verified`, `rejected`, `ambiguous`, `unsupported`. The orchestrator
skips bindings with `ambiguous`/`unsupported`/`rejected`. If
`tier3-search` reports "all seeds failed to compile," the bridge is
likely wrong for that function — `debug var-to-virtual` lets you
inspect the mappings interactively.

### Tracking Tier 3 matches

Commits where tier3-search produced the winning seed should include:

```
Tier3-Search: <seed-description>
```

as a trailer (analogous to `Co-Authored-By:`). A future
`debug tier3-stats` can count via `git log --grep "Tier3-Search:"`.

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
