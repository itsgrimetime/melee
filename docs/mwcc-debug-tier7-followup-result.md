# Tier 7 followup — validation result

The mwcc-debug agent shipped the requested tools (`rank-callees`, `ceiling`, `stuck`, `param-iter-ceiling` pattern entry, `enumerate-decl-orders --iterate`) and they work as designed. Tested on the two stuck functions from the earlier writeup.

## fn_80248A78 (98.94%)

`debug rank-callees` output:

```
   ig_idx  phys  predict  deg  notes
       87  r31       r31   13
       74  r31       r30   12  got r31 not r30
       ...
       34  r30         -   14  param-like (low ig_idx)
       32  r30         -   23  param-like (low ig_idx)
```

The "param-like (low ig_idx)" tag + the note at the bottom flag the ceiling explicitly. `debug ceiling fn_80248A78` returns `VERDICT: PROBABLE CEILING`. `debug stuck` ranks next steps by cost and recommends `enumerate-decl-orders` (already exhausted), then permuter (plateaued).

## fn_802487A8 (95.22%)

Same diagnosis — three locals with `ig_idx` 33–55 win the top 5 callee-saves, leaving the parameter (ig_idx 32) at r27. `ceiling` returns `PROBABLE CEILING` here too. (Plus the separate int-to-float magic constant naming issue, but that's a known Tier 6 case independent of this.)

## Validation of the param-iter-ceiling pattern entry

The `pattern-catalog param-iter-ceiling` text matches what we observed exactly. Notably it lists the things we tried that DON'T work (aliases, volatile, address-of, decl-reorder), which is the kind of pattern documentation that saves future investigators hours.

The only thing I'd add to that entry: the rare cumulative-decl-order finding. On fn_80248A78, applying `+0.04% promote temp_y` and `+0.04% demote spacing_pre` got us from 98.85% → 98.94% (still no jump past the ceiling). These are below the default 0.10% threshold but stack to be barely visible. `enumerate-decl-orders --iterate-threshold 0.01` finds them.

## Open thing from my earlier writeup that's still open

> **Could `coalescenodes` be nudged to merge the parameter's virtual with a high-ig_idx local's virtual?**

Both `ceiling` and `pattern-catalog` flag this as Tier 6 territory but don't enumerate the production-matching path. If the path is "DLL hook for coalescenodes", that'd close several stuck functions at once — fn_80248A78 (98.94%), fn_802487A8 (95.22%), and probably others outside mnvibration.c.

## Final state of mnvibration.c

| Function | Match | Status |
|---|---|---|
| mnVibration_802474C4 | 100% | matched |
| fn_80248084 | 100% | matched |
| mnVibration_802480B4 | 100% | matched |
| mnVibration_8024829C | 100% | matched |
| mnVibration_80248644 | 100% | matched (decl-reorder win earlier this session) |
| fn_80248748 | 100% | matched |
| mnVibration_80249174 | 100% | matched |
| mnVibration_80248ED4 | 100% | matched (string-via-offset + named-float wins earlier) |
| fn_80248A78 | 98.94% | param-iter-ceiling (Tier 6) |
| mnVibration_80248444 | 95.12% | int-to-float magic ceiling (Tier 6) |
| fn_802487A8 | 95.22% | param-iter-ceiling + magic (Tier 6) |
| fn_80247510 | 83.4% | multiple issues; needs /understand pass first |

10 of 12 matched. Two stuck at the ig_idx ceiling, one stuck at the magic-constant ceiling, one too low to be permuter-productive without prior structural work.

## Closing observation

The Tier 7 toolkit + the new `rank-callees` / `ceiling` / `stuck` / pattern catalog made the path from "stuck function" to "diagnosed ceiling with verdict" go from days to minutes. That feels like the actual goal of this tooling track — not just "find more wins" but "stop spending time on un-winnable cases."
