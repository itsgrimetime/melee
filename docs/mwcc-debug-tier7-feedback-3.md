# Tier 7 feedback-3 — `ceiling` produces false-positive WIN AVAILABLE verdicts

Quick note from one more session — found a bug class in the `ceiling` command's verdict logic.

## The bug

`debug ceiling mnVibration_80248444` reports:

```
[1] Cast audit (free, ~ms)...
    ! 1 HIGH-severity cast(s) found:
      - line 537: (f32) name_flag → HSD_JObjReqAnimAll

[2] Decl-order enumeration (promote strategy, ~minute)...
    No decl-order win found (8 candidates).

== VERDICT: WIN AVAILABLE ==
  Drop 1 HIGH-severity cast(s) — run `melee-agent debug suggest-casts mnVibration_80248444` for details.
```

But dropping the cast at line 537 is a NO-OP — match% stays at 95.12% before and after. The cast is on `(f32) name_flag` passed to `HSD_JObjReqAnimAll(jobj, f32 frame)`. Removing the explicit cast leaves an implicit u8→f32 conversion that compiles to the same int-to-float dance, the same f1 register load, the same call. Match% doesn't move.

So the verdict "WIN AVAILABLE" overstates what's available. It's a verdict based on the LINT, not on actual cost-test of the change.

## Root cause hypothesis

`suggest-casts --asm` says "ASM arg loads: f1=float, r3=int, r4=int, ...". This tells you arg1 of the call is loaded as float. The HEURISTIC in suggest-casts probably is: "(f32) cast on a value that becomes float in ASM is suspicious because the cast is redundant." But "redundant" doesn't mean "removable for match" — MWCC's codegen produces the int-to-float magic constant load + fsubs whether the cast is explicit or implicit. The match% is identical.

The lint flags it as HIGH. The `ceiling` command sees a HIGH-severity cast and infers "fix available." But these are different conditions:

- HIGH-severity cast that's WRONG (e.g. cast on variadic int arg that loads as int) → match% improves when dropped
- HIGH-severity cast that's REDUNDANT but BEHAVIORALLY SAME (e.g. cast on typed float arg) → match% doesn't change

The ceiling command conflates the two.

## Real test (cheap)

A more accurate verdict requires *actually testing* the cast drop. `verify-perm` does this for permuter candidates; the same machinery could drop the cast, compile, check match%, revert, report. About 6 seconds per cast.

For functions with 1-2 suspicious casts (which is most), this would be cheap to do automatically inside `ceiling`. Suggested behavior:

```
[1] Cast audit (~5sec including verify)...
    ! 1 HIGH-severity cast — auto-verified:
      - line 537: (f32) name_flag → HSD_JObjReqAnimAll
        drop test: 95.12% → 95.12% (no change, false positive)

[2] Decl-order enumeration (promote strategy, ~minute)...
    No decl-order win found.

== VERDICT: PROBABLE CEILING ==
  No verified wins. Move on or escalate to Tier 6.
```

Same true-WIN cases still report:

```
[1] Cast audit (~5sec including verify)...
    ! 1 HIGH-severity cast — auto-verified:
      - line 231: (f32) rumble_setting → lb_80011E24
        drop test: 73.8% → 75.5% (+1.7%, WIN — apply with --apply-casts)

== VERDICT: WIN AVAILABLE ==
```

Adds a few seconds to `ceiling` but produces verdicts with no false positives.

## Related: `suggest-casts` could itself rank by verified delta

Currently `suggest-casts` returns ALL casts at chosen severity (filtered by heuristic). If it also auto-verified each by drop+compile+diff, it could rank by ACTUAL match% impact:

```
$ melee-agent debug suggest-casts mnVibration_80248444 --verify
Function: mnVibration_80248444
Cast candidates (3 found, ranked by verified delta):

  line 537: (f32) name_flag → HSD_JObjReqAnimAll
    severity: HIGH (heuristic) / VERIFIED-NEUTRAL (drop test +0.00%)
    Recommendation: keep cast (lint false positive)
  ...
```

This gets even more value out of the lint by separating "looks suspicious" from "actually wrong."

## Current state of mnvibration.c

Unchanged from feedback-2 — three functions at the param-iter / magic-constant ceilings, one at 83.4% needing deeper structural work. Waiting on the coalescenodes hook.
