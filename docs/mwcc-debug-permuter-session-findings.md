# Permuter-driven matching session — findings for the debugger agent

This document is a writeup for the agent owning the `mwcc-debug` /
permuter integration work, based on a single session that used the
`debug pcdump / analyze / score / derive-target / guide` toolkit
alongside `decomp-permuter` to push four mnvibration.c functions
forward. The headline is that the permuter, fed our local
`permuter_settings.toml`, did most of the heavy lifting, but the new
debug commands were essential at two specific points and have clear
extension paths to make the loop tighter.

This is intended as a peer report — please read it as "here's what we
learned, here's what frustrated us, here's where you'd take it next" and
push back wherever I've misunderstood your tools.

## TL;DR

| Function | Start of session | After permuter+debug toolkit |
|----------|------------------|------------------------------|
| mnVibration_80248644 | 99.5% (declared "structural ceiling") | **100%** |
| mnVibration_80248ED4 | 81.6% | **100%** |
| fn_802487A8 | 87.4% | 94.0% (in progress) |
| fn_80247510 | 73.8% | 83.4% (in progress) |

The permuter found the mnVibration_80248644 fix in ~2000 iterations from
a slot-inline seed. The fix was a one-line declaration reorder — moving
`s32 j;` to be the first local. That was, in hindsight, completely
invisible from the analyzer's IGNode-level reasoning. Multiple prior
sessions had concluded "structural ceiling, source can't fix this."

## The recurring patterns the permuter found

Across the four functions, the permuter kept rediscovering the same
small family of source mutations:

### 1. Alias-into-fresh-local-to-split-a-live-range

The mutation that won the most often. Example from fn_802487A8:

```c
// Before
mnVibration_802480B4((HSD_JObj*) var_r26, var_r24, 1);

// After
new_var = var_r24;
// ... some intervening code ...
mnVibration_802480B4((HSD_JObj*) var_r26, new_var, 1);
```

The alias forces MWCC to materialize `var_r24` into a fresh virtual at
the point of `new_var = var_r24`, which gives that virtual a much
shorter live range (death at the bl call) than the original variable.
The original `var_r24` keeps going for its other uses. With one fewer
long-lived callee-save virtual, the allocator packs the rest tighter.

We collected three of these aliases in fn_802487A8 alone (`new_var`,
`new_var2`, `new_var3`) — each splitting a different live range.

### 2. Widen u8 → u32 to eliminate implicit promotion

```c
// Before
u8 var_r23;

// After
u32 var_r23;
```

When a u8 loop counter is used in many u8 expressions, MWCC emits a
clrlwi (or rlwinm) at every use. Widening to u32 removes the masks. In
fn_802487A8 this collapsed several rlwinm instructions and freed a
register, dropping us from 11 callee-saves to 10 (and combined with the
chained init, eventually to the expected 9).

### 3. Shrink s32 → u8 for value-bounded variables

The mirror of #2: when a variable's actual value range is 0..0xFF but
it's declared `s32`, MWCC may keep it in a callee-save with full 32-bit
arithmetic. In fn_80247510, switching `s32 name_idx` to `u8 name_idx`
collapsed a couple of clrlwi-after-bl patterns. Same trick, opposite
direction, same mechanism.

### 4. Drop unnecessary `(f32)` casts on variadic args

```c
// Before
lb_80011E24(jobj, &panel_jobj, 2, -1, (f32) rumble_setting);

// After
lb_80011E24(jobj, &panel_jobj, 2, -1, rumble_setting);
```

`lb_80011E24` is variadic. The decompiled source had an explicit `(f32)`
cast on what was actually being passed as an integer in the expected
ASM. The cast triggered an int-to-float conversion (including the
anonymous int-to-float magic constant) that wasn't supposed to be there.
Removing it bought us 1.7% match on fn_80247510. This is the kind of
thing a careful reader could have caught — but neither m2c nor the
analyzer flagged it.

### 5. Subexpression extraction into a named local

```c
// Before
HSD_JObjSetTranslateY(
    cursor_jobj, (HSD_JObjGetTranslationY(data->jobjs[18]) -
                  HSD_JObjGetTranslationY(data->jobjs[17])) *
                         (f32) data->x0[1] +
                     HSD_JObjGetTranslationY(data->jobjs[17]));

// After
dy = HSD_JObjGetTranslationY(data->jobjs[18]) -
     HSD_JObjGetTranslationY(data->jobjs[17]);
HSD_JObjSetTranslateY(
    cursor_jobj, dy * (f32) data->x0[1] +
                     HSD_JObjGetTranslationY(data->jobjs[17]));
```

MWCC's FP scheduler treats the named local as a single computed value
to schedule, vs the original which it might compute twice or schedule
differently. In fn_80247510, two such extractions (one in up-nav, one
in down-nav) bought us 7.4% match.

### 6. Declaration order — the big surprise

The mnVibration_80248644 win was *only* declaration order — moving
`s32 j` to be the first local. No body changes at all.

This was a real surprise. The analyzer's `candidates` reasoning ("j
could have been r29 if r27 were excluded") never connects to "what
makes MWCC encounter j first in its symbol table." The decl-order
effect propagates from parse → symbol table → ENode allocation →
IGNode allocation → simplification order → coloring choice. Five
indirection steps. Random mutation found it; structured reasoning was
looking in the wrong layer.

### 7. Chained init: `var_a = (var_b = 0);`

Cheap two-init combiner. In fn_802487A8 this dropped a callee-save
because the second `0` didn't need its own virtual.

## What the new debug tools did well

- **`debug pcdump` + `debug analyze`** were how I formed every
  hypothesis. The live-range and interference output is the right
  shape — when you can tell at a glance "j has 7 interferers and 4
  candidates," it's much easier to know whether a mutation is moving
  things in the right direction.

- **`debug diff` between two pcdumps** caught register cascades far
  faster than reading raw asm diffs. The "X removed, Y added,
  Z changed phys" summary is the one I reached for repeatedly.

- **Tier 5 `--force-phys`** gave me confidence that "the target is
  reachable" before spending hours on source variations. For
  mnVibration_80248644, running `--force-phys "36:31"` and seeing the
  byte-perfect match was the moment I knew it was worth grinding on.

- **`derive-target`** captured the post-force-phys state cleanly. I
  didn't end up using it as a permuter scorer (more on that below) but
  it was useful for "what's the expected mapping I'm aiming for."

## What was frustrating / where the loop wasn't tight

### Permuter winners that don't transfer to source

Several times, the permuter found a `score 1320` (better than the
`1455` baseline) and writing the diff to source compiled to the *same*
match% as before applying. The permuter's preprocessed `base.c` and the
real ninja build have subtly different surrounding context — function
visibility, macro expansion, asserts — and a mutation that helps in the
stripped version doesn't always survive transplant.

**Suggestion:** a `debug verify-perm <path/to/output-NNNN-N/>` command
that takes the permuter's `source.c`, extracts the changed function,
patches it into the real source tree, recompiles via ninja, and reports
"actual match% vs permuter's claimed score." Would let us prune
non-transferring winners without manual copying.

### Decl-order mutations are huge but ungoaled

The permuter found the mnVibration_80248644 decl-order fix by chance.
But declaration order is a small, enumerable space: in a function with
N locals, there are at most N! orderings, and only a few hundred have
distinct effects (most reorderings preserve semantics + codegen). A
dedicated pass that enumerates decl orderings would find this kind of
fix in O(N) iterations instead of O(2000).

**Suggestion:** a `debug enumerate-decl-orders <fn>` command that
generates the N candidate sources and runs each through ninja+checkdiff,
reporting any that improve. Could be a permuter "mode" too.

### `(f32)` cast / variadic mismatches are static-checkable

The `lb_80011E24(... (f32) rumble_setting)` cast that was wrong is
something a static analyzer could flag without compilation:
"variadic call with explicit cast to a type the expected ASM doesn't
load — consider dropping the cast." We'd need the expected ASM in
scope, but the project already has it.

**Suggestion:** a `debug suggest-casts <fn>` that diffs each call-site
argument's type-as-emitted between current and expected, flagging cast
mismatches. Probably one of the highest "win per CPU second" tools
since it doesn't require permutation at all.

### `debug guide` could be louder about decl-order

Currently `debug guide` reports per-virtual SPILLED/wrong-phys signals.
It correctly notes "r50 is on the edge" but doesn't suggest
*source-level* mutations. If guide knew the pattern catalog above, it
could say "this looks like a u8→u32-promotion situation; try widening
var_r23" or "your interference graph has a long-lived virtual that
would shorten if you moved its declaration first."

**Suggestion:** structure `debug guide`'s output as a ranked list of
*pattern names* from the catalog, with "would-suggest" snippets. Keep
the analyzer-level output as `--verbose`.

### Permuter has a custom-scorer hook we haven't used

The `debug score` help string says "Designed to be called by
decomp-permuter as a custom scorer," but standard upstream permuter
doesn't have a custom-scorer interface. We're scoring by objdump diff,
which is the default. Plumbing this through would let us:

- Force-phys derive a target IGNode mapping
- Score candidates by IGNode-distance, not asm-distance
- Reward source mutations that move us toward the target IGNode layout
  even when the asm is "different but same score"

The expected matching ASM is one specific IGNode layout; the asm-diff
scorer treats all "different but same penalty count" candidates as
equivalent and can't tell which direction is closer to the goal IGNode
layout. An IGNode-aware scorer would gradient-descend properly.

**Suggestion:** a fork (or upstream patch) to decomp-permuter adding
`--external-scorer <command>` that calls our `melee-agent debug score`
with the per-candidate compiled .o. Currently we run the permuter
asm-blind. If the integration is non-trivial, even just a wrapper that
batch-runs `derive-target` on each output dir and reports
`IGNode-distance-from-target` would help me triage which winners are
worth applying.

## Specific small asks for the next tools iteration

These would each tighten one obvious friction point in our current
loop. Listed in rough order of "how often I hit the friction":

1. **Patternized `debug guide` output** — name the pattern, suggest the
   mutation. The catalog above is a starting list.

2. **`debug verify-perm <output-dir>`** — apply a permuter winner to
   the real source and report actual match%. Stops the "permuter says
   1320 but my checkdiff says no change" cycle.

3. **`debug enumerate-decl-orders <fn>`** — N! decl-order space is
   small enough to brute-force. Would auto-find the mnVibration_80248644
   class of fix.

4. **`debug suggest-casts <fn>`** — static lint over call-site cast
   types vs expected. No compilation needed.

5. **Permuter `--external-scorer` integration** — wire `debug score`
   into the permuter loop. Let the permuter gradient-descend on
   IGNode-distance.

6. **`debug pattern-catalog`** — dump the known mutation patterns
   (alias, widen, shrink, decl-reorder, subexpr extract, drop-cast,
   chained-init, ...) so the catalog is a first-class artifact in the
   project, not just notes in docs and memory.

## What I'd love a second opinion on

- **Is decl-order really enumerable in practice?** I've been assuming
  most reorderings don't change codegen, but the parse-order effect is
  more subtle than that. If MWCC's symbol table allocates ObjObjects
  in declaration order, every reordering matters. If so, the "N
  candidates" claim is wrong and it's closer to "ON(N!) but most are
  equivalent." Would need empirical data.

- **The "permuter winner doesn't transfer" issue** — is it really
  base.c vs real-tree differences, or is there a stochastic element
  in MWCC that the permuter is being tricked by? If the latter, that's
  much harder to fix.

- **For the IGNode-distance scorer:** what's the right metric? Hamming
  distance over virtual→phys mappings, weighted by virtual's degree?
  Something more clever?

The session that produced this writeup is on `wip/mn-heartbeat`. Recent
commits document each individual mutation we applied; happy to walk
through any of them.
