# mwcc_debug — future improvement ideas

The current tooling answers "which register did MWCC pick" and (with the
analyze command) "what were the constraints" — but not "why this register
specifically." These are notes on what we could build next to close that
gap. Not detailed designs; just enough that we don't re-derive the ideas
from scratch later.

## Tier 2 — hook MWCC's register-allocator entry point

The patched DLL currently hooks three functions (`pclistblocks`,
`pcode_traverse`, `listing_helper`) to dump per-pass IR. The biggest
remaining unknown is the allocator's *decision logic*: given that r36
could have been any of {r27, r28, r30, r31}, why r27?

A new hook on the function MWCC calls to pick a physical register for a
given virtual (something like `chooseRegister(virtual, class, candidates)`
or `assignReg(virtualReg)`) would let us log the candidate set, the
chosen physical, and any cost/preference fields the allocator evaluated.

**What it unlocks:** definitive answer to "why r27 not r31" without
having to reverse-engineer the allocator from observed behavior.

**Rough path:** Use Ghidra on `build/compilers/GC/1.2.5n/mwcceppc.exe`
to find the allocator entry point. It should be reachable from / near
the existing `0x4C2560` (`pcode_traverse`) — the coloring pass probably
calls something like `assignPhysical(pcode_t *)` per pcode. Add the VA
to `tools/mwcc_debug/mwcc_debug.c`, write a hook that captures
`(virtual_reg, class, candidates, chosen)` and emits a line to
`pcdump.txt` after each call. Rebuild DLL, redeploy to Windows host.

**Effort:** ~1 day, mostly Ghidra exploration.

## Tier 3 — cross-reference MWCC 7.0 source

The mwcc_debug upstream README points at <https://git.wuffs.org/MWCC/>
— a decompilation of MWCC v7.0 targeting MSL_MacOS. Different version,
same architectural lineage. The register allocator code there is likely
similar enough that:

- We could identify the function name + signature of the coloring entry
  point in the 7.0 source.
- Then find the analogous code in our 1.2.5n binary much faster (same
  Ghidra task as Tier 2 but with an oracle).
- And read the actual cost/preference function to know what factors
  influence the choice — could even build a small *symbolic simulator*
  that predicts which register would be picked given a virtual-reg
  numbering and use-count distribution.

**What it unlocks:** the algorithm becomes legible, not just observable.

**Rough path:** Spend an afternoon reading the 7.0 source around
`register*` / `color*` / `allocate*` files. Document the algorithm in
prose. Use that as the guide for Tier 2's Ghidra hunt. Optional: write
the simulator as a Python module that takes the analyze command's output
and predicts the assignment.

**Effort:** Half-day for the read; ~1 day for the simulator if pursued.

## Tier 4 — permuter integration

[Decomp Permuter](https://github.com/simonlindholm/decomp-permuter) does
randomized C-source mutation, recompiles, scores against target asm.
It's the heavyweight tool people reach for when nothing else moves the
needle (inspector's `GOAL.md` mentions 50,000+ iterations on
`mpColl_80046904` without finding a beating local minimum).

The permuter is random by design. With our pcdump output + analyze
command, we could make it smarter — after each candidate, examine the
dump to see whether the mutation moved any of:
- A virtual register's live range (toward or away from the target)
- The use count of a virtual that's at the wrong physical
- The interference graph

A *guided* permuter that prefers mutations that affect the right
virtuals would converge much faster than random. Likely needs a custom
permuter scorer that incorporates the analyze output.

**What it unlocks:** systematically explorable "stuck at 99.8%" cases,
rather than stochastic.

**Rough path:** much bigger build. Implement as either (a) a new scorer
plugin for permuter that calls our analyze command, or (b) a separate
guided-search tool that owns its own mutation loop. (b) is cleaner but
re-implements a lot of permuter's machinery.

**Effort:** week-plus, depending on how deep the integration goes.

## Tier 5 — speculative: directly modify the DLL to bias coloring

The patched DLL already injects code into mwcceppc's address space. In
principle we could go further: not just observe the allocator but *bias*
it — e.g. force a specific virtual to a specific physical, or change
the candidate ordering.

This would let us answer "what if r36 got r31?" by actually compiling
that variant and diffing. It's the most invasive change (we'd be
modifying the compiler's behavior, not just observing it) but it's also
the most direct path to confirming hypotheses about the allocator.

**What it unlocks:** ground-truth answers via experimentation.

**Risks:** harder to know whether a forced-mapping result reveals a
real allocator preference or an artifact of our bias. Need careful
experiment design.

**Effort:** depends on what we want to bias; ~day per knob.

## Other small wins not worth their own tier

- **JSON output mode** for the analyze command — easier for agents to
  consume programmatically.
- **Comparison mode**: given two pcdumps (e.g. a passing-attempt and a
  failing-attempt for the same function), diff just the coloring
  decisions to surface what changed.
- **ABI annotation** in the analyze command — show "r3 = arg0", "r4 =
  arg1" etc. derived from function signature so the caller-save
  candidate filtering accounts for argument pinning.
- **Live-range alignment improvements** — the current pre/post-pass
  alignment is naive (skip-forward on opcode mismatch). Could use a
  proper sequence-alignment algorithm (e.g. Smith-Waterman variant) to
  recover more virtuals' live ranges from passes that re-order
  instructions.
