# mndiagram3 matching results — 2026-09-05

Both remaining functions were completed in [PR #3355](https://github.com/doldecomp/melee/pull/3355).
The source commit on the clean upstream branch is `0e1b216de7`; the symbol-scope
follow-up is `37887544a4`. The working branch source commit is `187d073f3f`.

| Function | Starting match | Final match |
| --- | ---: | ---: |
| `mnDiagram3_PopulateRankings` (`80245BA4`) | 97.91282% | 100% |
| `mnDiagram3_HandleInput` (`802461BC`) | 99.72863% | 100% |

All nine functions and all 272 data bytes in `mndiagram3.c` match. All 21
functions in `mndiagram2.c` remain matching. Validation used the unforced retail
GC/1.2.5n build configuration. `python configure.py && ninja` passed the original
`main.dol` SHA-1 check both in the working checkout and on the clean PR branch
based on upstream `fa69daf6a1`.

## What the large inline move actually did

The original function order is `PopulateRankings`, `HandleInput`,
`UpdateScrollArrows`, then the remaining functions through `Init`. The partial
source had `HandleInput` at the bottom. Moving it after `PopulateRankings`
restored the emitted `.text` order. Its inline helpers moved with it to keep
fully defined helpers before their caller. Their exact textual position was
not the demonstrated register-allocation fix.

A controlled follow-up moved the entire final helper/handler block back to EOF,
without changing its bodies. `HandleInput` still scored 100%, but its ELF
function symbol moved after `Init`, and `ninja` failed the DOL checksum.
Restoring the PR order restored `main.dol: OK`. The source was restored after
the experiment; no probe was pushed. Preserved evidence is in
`docs/matching-evidence/mndiagram3/function-order-experiment.json`, with adjacent
build logs. These artifacts are committed with the fork notes.

The semantic helper changes were distinct from that relocation:

- `GetRowSpacing`, `ClearRowLabels`, and `RefreshRankings` already existed.
- New `GetRowStat` isolated index wrapping behind `u8` parameters and a `u8`
  return. This corrected allocation in all three row-label rebuild loops.
- New `PositionPopup` isolated the repeated cursor positioning. Its exact call
  expression mattered, not just extracting a helper.
- `GetPopupY` gained an actual row-index parameter to preserve the original
  floating-point calculation when called with row zero.

## PopulateRankings: types and expression shape

Expose the existing `mnDiagram2_SortEntry` union in the header and use it for
both the output parameter and the three caller result objects. Keep the API as
`void GetAggregatedFighterRank(mnDiagram2_SortEntry* out, u8 type, u8 idx)`;
write `*out = entries[idx]`. A struct-return experiment was not retained.

The final caller has `Vec3 position` first, `unit_glyph_ids` last, three distinct
rank objects, and direct `.idx`/`.xC` accesses. This restores the 240-byte frame
without the previous `PAD_STACK(8)`. Types, alignment, declaration placement,
and expression shape worked together; this does not prove a hidden struct-return
ABI or a universal frame formula. Keep the existing narrow second-rank form
`u8 rank = (u16) i`: normalizing all three casts caused unwanted CSE of the rank.

Passing `GetNameText(entity)` directly to the variadic text call fixed the
required argument transfer. Literal `0.035f`, `1.5f`, and `1.0f`, plus direct
`-position.y` in the unit-text call, avoided several unnecessary held values.

An especially useful controlled observation: after replacing the named zero
constant, retaining `f32 f1 = 0.0f` at the two value-text call sites produced an
extra saved FPR, a 248-byte frame, and a 97.44% match. Passing `0.0f` directly to
those calls restored 100% and 240 bytes. Literal-to-local rewrites can therefore
help or hurt; inspect the actual `lfs`/`fmr` and save/restore changes.

## HandleInput: the successful boundary and argument combination

With `GetRowStat` in place, the function reached about 99.89%. Only the cursor
row and data pointer swapped r26/r30 in both cursor-movement branches.

The successful shape was:

```c
static inline void PositionPopup(HSD_JObj* popup, u8 row, Diagram3* cur)
{
    f32 spacing = GetRowSpacing(cur);
    /* Existing X/Y/Z getters and setters; Y uses spacing * (f32) row. */
}

popup = data->popup_gobj->hsd_obj;
PositionPopup(popup, data->cursor_row,
              cur = mnDiagram3_804D6C20->user_data);
```

Staging `cur` in a preceding assignment and then passing it was not equivalent
for MWCC allocation: that variant remained around 99.79%. Embedding its
assignment in the third argument removed all register differences, leaving only
the position-vector stack slots (about 99.99%). This is measured source
sensitivity; do not assume raw virtual-register IDs survive a source change.

The original input handler already reserved 76 bytes of `PAD_STACK`, distributed
32/12/8/24 across the root/mode/up/down scopes. The final source keeps the same
total, redistributed 32/16/12/16 after removing unused helper locals. The final
no-padding control has a 248-byte frame versus the target's 320; the three Vec3
slots must also stay at 0xDC, 0xC0, and 0xA4. Earlier intermediate sources had a
256-byte no-padding frame: do not copy that number into the final-source notes.
The remaining reservation gap is documented, not claimed to reconstruct the
original declarations completely.

## Literal pool and the already-matched initializer

Per-function scores did not establish a linkable TU. Removing duplicate named
float definitions and extending `sdata2_order` produced the exact 40-byte pool:
U32 conversion bias, 6.5f, 240.0f, S32 conversion bias, 0.035f, 0.0f, 1.5f, 1.0f.

Directly changing `GetPopupY` to `spacing * 0.0f + GetY(row)` regressed the
already-matched `Init` to 97.37387%. MWCC removed spacing loads/subtraction and
the original multiply-add. This natural parameterization restored it:

```c
static inline f32 GetPopupY(HSD_JObj* row, f32 spacing, u8 index)
{
    return spacing * (f32) index + HSD_JObjGetTranslationY(row);
}
/* Initial position: GetPopupY(row, spacing, 0). */
```

This kept `Init` at 100%, frame 152, and avoided an extra named/anonymous zero.
It is a compiler-phase observation on this source, not a claim that all inline
constant parameters resist propagation. A generic zero getter did not work.

## Failed approaches worth avoiding on the same baseline

- Index type swaps, caller declaration permutations, generic data getters,
  carrier structs, and moving the entire cursor block into various helper
  signatures did not solve the final pair by themselves. Some fixed one register
  but introduced a different swap or extra frame homes.
- The two-argument popup helper fixed the row register but swapped popup/data;
  the three-argument helper needed the embedded data assignment as well.
- Struct-return ranking results were close but failed stack layout. Use the
  verified typed output-pointer API.
- Replacing the row-label byte base with a typed whole-table pointer caused
  different address hoisting/register allocation. That cleanup was reverted.
- A bounded select-order search and roughly 13 minutes of a permuter run on an
  earlier source did not improve the real match. They do not establish a source
  ceiling; the later manual helper/argument combination succeeded.
- Force-phys/proxy wins are diagnostics only. Refresh the actual object and
  dump, track value identity rather than raw IG numbers, and recheck real code.

Tool observations were filed as issues: #1440 (permuter chose a stale shared
path), #1446 (select-order proxy reused drifting IG identities), #1447 (format
wrapper missing an argument), and #1449 (doctor overwrote a tracked upstream
helper while hydrating a PR worktree). Restore such unrelated bootstrap changes
before publishing. Fresh upstream had changed include conventions; the PR was
adapted and rebuilt there, not merely cherry-picked and assumed valid.

## Searchable mismatch entries and stale conclusions

The shared mismatch database now has these entries, with successful-function
provenance:

- `typed-aggregate-output-restores-caller-frame`
- `inline-boundary-embedded-argument-coloring`
- `direct-float-call-literal-avoids-loop-hoist`
- `inline-u8-index-preserves-zero-position-fmadd`
- `function-body-match-does-not-prove-text-order`

Also recorded success against existing `inline-call-result-vs-named-local`.
The first new entry explicitly supersedes the old `frame-arg-area-overreservation`
entry's no-source-lever conclusion for `mnDiagram3_80245BA4`. Historical campaign
notes about these two functions being stuck are superseded by this verified
result; their negative experiments remain useful only for the source shapes
actually tested.
