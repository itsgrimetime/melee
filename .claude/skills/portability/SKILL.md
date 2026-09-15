---
name: portability
description: Triage and implement Melee portability fixes exposed by native builds or runtimes, including LP64 pointer widths, host compiler failures, endian behavior, undefined behavior, and PPC-versus-host semantic differences. Use when deciding what belongs upstream versus in a port; do not use for ordinary cleanup without a portability finding.
---

# Melee Portability

Use native builds and runtimes to expose inaccurate source abstractions while
preserving the GameCube binary. The main decomp should own portable semantics
and interfaces; each port should own its host-specific implementation.

## Triage the Finding

Trace the value or behavior through every important producer, consumer, stored
field, cast, serialized representation, and target call before choosing a fix.
Classify it into one of these groups:

1. **Source defect:** an incorrect declaration, pointer truncation, undefined
   behavior, or raw target-layout assumption. Fix this in the main decomp.
2. **Missing abstraction:** the program has a real concept that needs different
   target and host representations. Add the smallest type, accessor, or
   interface here; keep the host implementation in the port.
3. **Port implementation:** DAT conversion, relocation and pointer widening,
   snapshot materialization, hardware or service stubs, headless boundaries,
   and host execution infrastructure. Keep this outside the main decomp.

Do not upstream a port patch merely because it makes one native experiment run.
The change must improve the source model or provide a reusable boundary.

## Model the Value Domain

- Keep file-format, protocol, MMIO, and target ABI words fixed-width.
- Use `uintptr_t` or a named pointer-width integer only when values can be
  derived from native pointers and must survive a round trip without loss.
- Do not widen an integer merely because it is adjacent to pointer arithmetic.
- When a value can mean a guest/ARAM address, file offset, or native pointer,
  model those domains explicitly or resolve them behind an accessor. A wider
  integer alone does not explain or safely implement the distinction.
- Check structure size, offset, alignment, hashing, comparisons, sentinel
  values, and serialized inputs after changing a field's width.

C type identity matters independently of width. MWCC may generate different
code for `unsigned int`, `unsigned long`, a pointer, and typedefs of the same
size. Verify proposed substitutions with the compiler and exact binary rather
than assuming equal size implies equivalent code generation.

## Choose the Boundary

- Prefer a named domain type when a value flows through multiple fields or APIs.
- If the portable representation is correct but matching requires the original
  source type, select the target representation with `MUST_MATCH`. Use
  `MWERKS_GEKKO`, compiler checks, or architecture checks only when behavior is
  genuinely specific to that compiler or architecture.
- Do not change a global primitive typedef to solve one local mismatch without
  auditing every user of that typedef.
- Explicit pointer-to-integer casts remain necessary while an API uses an
  integer key. Elide them only when the abstraction itself becomes pointer-like
  or the source expression is already the correct key type.
- Avoid replacing visible casts with macros or helpers unless the helper names a
  meaningful conversion or address-domain boundary.

For endian-sensitive bitfields, do not default to duplicated little- and
big-endian declarations. C bitfield allocation is implementation-defined.
Prefer masks, accessors, or a shared endian-aware representation supported by
both static layout checks and native runtime observations. Treat command words,
asset-backed flags, and unions with whole-word views as coordinated design
problems rather than isolated declaration reversals.

For floating-point differences, separate source-level undefined behavior from
intentional PPC semantics. Fused arithmetic, reciprocal-square-root estimates,
and related determinism usually need a compatibility boundary; do not scatter
host builtins through matched gameplay code.

## Validate Both Contracts

Establish a clean baseline in the active worktree before editing. Follow the
repository's decomp workflow for match-sensitive changes.

For every retained change:

1. Reproduce the native compile failure or runtime divergence that motivated it.
2. Run `python configure.py`, `ninja`, and `python configure.py progress`.
3. Require the expected GALE01 DOL hash and unchanged object, function, code,
   data, section, relocation, and linked metrics.
4. Run the relevant native compiler checks. If the claim is behavioral, run a
   focused native differential or controlled runtime test rather than treating
   successful compilation as proof.
5. Use an isolated experiment to test plausible reviewer alternatives. Record
   the exact compiler error or smallest mismatching function when an apparently
   equivalent spelling fails.
6. Run `git diff --check` and keep generated native artifacts out of the diff.

If native behavior improves but the target match regresses, reduce the change to
the responsible declaration or expression. Prefer a truthful `MUST_MATCH`
boundary over compiler tricks. If the portable design remains ambiguous, retain
the evidence and stop before opening a PR.

## Prepare an Upstream Change

Keep each PR centered on one type path, abstraction, UB fix, or layout
assumption. Do not combine port infrastructure or unrelated native cleanup.
Describe:

- the incorrect or missing abstraction;
- the target and host representations;
- the observed native failure or divergence;
- exact-match and native verification; and
- any intentionally external implementation work.

Every AI-assisted PR against `doldecomp/melee` must have the `ai-assisted`
label from creation. Add the `portability` label whenever portability is the
focus. Do not open, push, or reply to reviews unless the user authorized that
external action.
