# Tier 7 toolkit — session followup for the mwcc-debug agent

This is a second writeup, following [`mwcc-debug-permuter-session-findings.md`](mwcc-debug-permuter-session-findings.md), after using the Tier 7 toolkit (verify-perm, enumerate-decl-orders, pattern-catalog, suggest-casts, triage-perm) on fn_802487A8 and fn_80248A78 in `mn/mnvibration.c`.

**Headline:** the toolkit was exactly what we asked for — three concrete wins (+0.6% fn_802487A8 via triage chained-init, +0.9% fn_80248A78 via triage subexpr-extract, +0.2% fn_802487A8 via decl-order port_a promote) plus a clear characterization of the remaining ceiling that wouldn't have surfaced otherwise.

## What worked best in practice

1. **`triage-perm --apply-best`** was the highest-leverage tool. Took an
   accumulated permuter run (95–146 candidates) and identified the
   one or two that actually transfer to the real source tree. Both
   triage finds this session crossed the +0.1% threshold and produced
   real match% improvement.

2. **`enumerate-decl-orders`** found a +0.19% win on fn_802487A8 that
   the permuter had spent ~3000 iterations on without finding. The
   space is small and brute-forceable; the permuter wastes cycles
   re-exploring it randomly.

3. **`pattern-catalog`** as a reference doc — when applying triage
   winners, I could verify "this is the alias-split pattern" before
   committing, which made the commit messages much clearer (and made
   me more confident the mutation wasn't a phantom).

4. **`suggest-casts --asm`** had no true positives on these functions
   (every `(f32)` cast it flagged was correct for a variadic-with-float
   arg) but the ASM cross-ref made it fast to disambiguate — I trusted
   the output enough to drop the cast on three sites in fn_80247510
   in the prior session.

## What surfaced a new ceiling

After getting fn_80248A78 to 98.9% and fn_802487A8 to 95.1%, both
plateaued. The investigation that followed (force-phys + analyze +
COLORGRAPH DECISIONS read) identified a **new structural ceiling
distinct from the interference-based one**:

### The ig_idx-descending iter order ceiling

`COLORGRAPH DECISIONS` shows the coloring iter order. Within saved
nodes that need callee-save dispense, MWCC iterates by **IGNode index
descending**. Iter 0 gets `r31`, iter 1 gets `r30`, etc.

**Parameters always have the lowest ig_idx** (created at function
entry). Locals get higher ig_idx (created at first use during body
parse). So when a parameter and a long-lived local both compete for
top callee-saves, the local wins every time.

For fn_80248A78:
- `r48` (user_data, ig_idx 48) → iter 0 → `r31`
- `r32` (arg0/gobj, ig_idx 32) → iter 1 → `r30`

Expected wants them swapped (gobj at r31, user_data at r30). Force-phys
`"32:31,48:30"` produces byte-perfect target. Confirms the target is
reachable. But no C-source pattern I found will swap their ig_idx
ordering because the parameter is structurally first.

For fn_802487A8 the same ceiling applies but with a 4-position
cascade — THREE long-lived locals (HSD_PadCopyStatus base,
mn_804D6C28 cache, mnVibration_804D4FE8 walker) all have higher
ig_idx than gobj and pile up at r29/r30/r31. Gobj falls to r27.

Documented in [`mwcc_ignode_ordering_ceiling.md`](../../../.claude/projects/-Users-mike-code-melee/memory/mwcc_ignode_ordering_ceiling.md) — note this is **distinct from** the
existing interference-based ceiling in
`mwcc_allocator_interference_ceiling.md`. They have different
diagnostic signatures and different fixes.

## Specific tool asks

In order of leverage:

### 1. `debug rank-callees <function>` — cheap, high signal

List all callee-save virtuals sorted by ig_idx descending. For each,
show its live range, predicted phys (top-down dispense from r31), and
which "competing" virtuals would have to be removed for the named one
to move up.

Example output for fn_80248A78:

```
fn_80248A78 callee-save IGNode ranking (top-down dispense order):
  iter 0  r48  user_data   ig_idx=48  live[1..124]   → r31
  iter 1  r32  arg0/gobj   ig_idx=32  live[0..270]   → r30  (PARAMETER)
  iter 2  r43  …           ig_idx=43  live[…]        → r29
  …

  To put r32 (parameter) at r31, you need its ig_idx to exceed all
  competing saved-node virtuals. Currently 1 local outranks it.
  Note: parameter ig_idx is generally fixed at function entry.
```

The "PARAMETER" tag flags the structural ceiling. The
"X locals outrank it" count tells the agent how much restructuring
would be needed.

This is just the existing `analyze` data, reformatted for the
specific question.

### 2. `debug guide` pattern catalog entry for this ceiling

Add a `param-loses-to-local` (or similar) pattern to
`pattern-catalog`. When `guide` is run with a target spec where the
parameter virtual is wrong-phys AND the wrong-phys is "below" all
the locals, cite this pattern explicitly with the
"Tier 6 territory" tag.

This stops investigators (humans or LLMs) from spending hours on
permuter runs that can't break this structural limit.

### 3. `enumerate-decl-orders --cumulative` or lower default `--threshold`

The default `--threshold 0.1` filters out wins under 0.1%. We have
two cases now where stacking `+0.04%` + `+0.04%` would have given
us `+0.08%` cumulatively — close to threshold but neither alone
qualifies.

Option A: `--threshold 0.04` works but is per-command. Could lower
default to `0.05`.

Option B: `--cumulative` mode that:
1. Enumerates as today
2. Finds best (any positive delta, no threshold)
3. Applies it
4. Re-enumerates from new baseline
5. Repeats until no improvement
6. Reports the final state vs original baseline

This would automatically stack small wins — useful when each is
below the threshold but together they meaningfully help.

### 4. `debug triage-perm --minimal-diff`

Today triage's `--apply-best` reformats the file via the permuter's
strip pipeline (loses doc comments, inline-keyword styling, brace
positions). I revert and re-apply manually each time.

A `--minimal-diff` flag could extract just the LOGICAL change (the
new decl + the edited expression) and apply it as a focused diff
against the existing source, preserving everything else. The `diff`
file is already there (`output-*/diff.diff`) — the tool could read
that, parse the hunks, and apply via `git apply --3way` or similar.

### 5. (Maybe) `debug ig-swap-cost`

Given a target spec, report:
- The minimum number of structural changes (reduce N callee-save
  virtuals, raise X ig_idx by N positions, etc.) that could
  plausibly produce the target.
- Whether any change is achievable from C source vs requires Tier 6.

Lower priority than the others — the rank-callees output gets you
most of this signal already.

## Open questions to bounce back

- **Is there ANY source pattern to raise a parameter's ig_idx?** My
  experiments with `HSD_GObj* gobj_late = arg0;` got coalesced away
  via the `mr`. If volatile/address-of/some-other-trick can force a
  fresh IGNode for the parameter, that'd close the ceiling. The
  pattern-catalog might already know about this.

- **Could `coalescenodes` be nudged to merge a parameter's virtual
  with a high-ig_idx local virtual?** If so, the merged virtual
  could inherit the higher index. Tier 5/6 territory but might be
  much cheaper than a full allocator patch. (Bisecting this in the
  DLL is the kind of thing your tooling is built for.)

- **The int-to-float magic naming** (`@472` vs
  `mnVibration_804DC018`) is a separate Tier 6 issue we've documented
  before. fn_802487A8 has one remaining instance of this. Not in
  scope for the above but worth keeping in mind when prioritizing
  tier-6 work — it caps ~2-3 functions in mnvibration.c at <100%
  regardless of cascade.

## Current state of the work

- mnvibration.c: 10 of 12 functions matched at 100%
- fn_80248A78: 98.9% — pure ig_idx ceiling
- fn_802487A8: 95.1% — ig_idx ceiling (cascade-4) + one int-to-float magic
- fn_80247510: 83.4% — multiple structural issues, needs `/understand`
  pass first; deferred
- mnVibration_80248444: 95.1% — int-to-float magic ceiling

Branch `wip/mn-heartbeat`. Recent commits document each mutation;
tag `permuter-stop` if/when we declare these final.
