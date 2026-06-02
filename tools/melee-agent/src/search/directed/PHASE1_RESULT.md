# Phase-1 Live Gate Result — grIceMt_801F9ACC

## Verdict

**PASSED** — `attributable_progress`

```json
{
  "gate": {
    "passed": true,
    "reason": "attributable_progress",
    "evidence": {
      "applied_mutator": "reorder_local_decls",
      "displacement": 1.0,
      "displacement_delta": 1.0,
      "n_treatment": 4
    }
  }
}
```

## Telemetry Summary

| Metric | Value |
|--------|-------|
| compiled candidates | 4 |
| valid treatment entries | 4 |
| case | C2 (C2_STICKY_POOL) |
| reanchor coverage | 2/2 (100%) |
| displacement | 1.0 (perfect — both target roles matched their objective positions) |
| displacement_delta | 1.0 (all beats control baseline of 0.0) |
| applied_mutator | `reorder_local_decls` |

## Force-Phys Derivation

The `GRICEMT_9ACC_FORCE_PHYS` map was pinned at Task 12 by live pcdump analysis:

```python
GRICEMT_9ACC_FORCE_PHYS = {33: 27, 40: 29}
```

- `ig_idx=33` → virtual reg r33 (param y float-shadow, `mr r33,r4` in BEFORE GLOBAL OPTIMIZATION pass), currently r29, desired r27
- `ig_idx=40` → virtual reg r40 (local `did=0`, `li r40,0`), currently r27, desired r29

Verified against expected assembly: expected has `addi r27,r4,0` + `li r29,0`; current has
`addi r29,r4,0` + `li r27,0`.

## Integration Fixes Applied During Task 12

1. **`DirectedScorePipeline.score_byte`** — Missing method. Added with injectable `byte_scorer`.
2. **`FunctionEvents` not iterable** — `compile.fev` is a `FunctionEvents`, not a list; wrapped in `[...]` before `find_function`.
3. **`should_escalate` always False** — With empty `byte_history`, tier-1-first never escalated. Fixed with `_AlwaysEscalate` subclass.
4. **`DirectedSearchState.identity`** — `classify_progress` received a `DirectedSearchState` as `prev` instead of an `IterationState`. Fixed with `_safe_classify` wrapper.
5. **`applied_mutator=None`** — Mutator key not flowing from `DirectedSource` provenance to `DirectedMeta`. Fixed by reading `art.provenance.mutation` in the scorer.
6. **`scheduler.py` promote dedup** — `seen.add(cand.candidate_id)` was placed before both directed and tier-1 promote paths, causing tier-1 recompiles to be deduped. Fixed by scoping `seen.add` to the directed branch only.
7. **C2_STICKY_POOL propose fallback** — Primary path returns `var_name=None` for sticky-pool divergence. Added fallback: enumerate adjacent local-declaration pairs and propose `reorder_local_decls` on each.

## Notes

The `displacement=1.0` result means the reordered-decl candidates compile with BOTH
target roles anchoring at their desired positions. This is the proof that the directed
mechanism can produce scored, attributed candidates for the 9ACC wall. The fallback
pair-enumeration path (not the primary var_name path) was used because `C2_STICKY_POOL`
divergence does not resolve a specific variable name. A Phase-2 search would iterate
over more decl pairs and apply heavier mutations to find a source change that moves
the register coloring.

## Run Command

```bash
melee-agent debug search directed \
  --function grIceMt_801F9ACC \
  --unit melee/gr/gricemt \
  --no-dry \
  --max-iters 4
```
