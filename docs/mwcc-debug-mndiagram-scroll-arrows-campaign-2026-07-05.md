# mwcc-debug campaign: `mnDiagram_UpdateScrollArrows`

Date: 2026-07-05

Function: `mnDiagram_UpdateScrollArrows`

Source: `src/melee/mn/mndiagram.c`

## TL;DR

`mnDiagram_UpdateScrollArrows` matched after treating the final diff as a
source-ownership problem for an implicit byte-address temporary.

The final down-fighter branch changed from this source ownership:

```c
ptr = sorted + i;
...
ptr2 = ptr;
...
ptr2++;
ptr++;
...
mn_IsFighterUnlocked(*ptr2)
```

to this equivalent ownership:

```c
ptr2 = sorted + i;
...
ptr = ptr2;
...
ptr++;
ptr2++;
...
mn_IsFighterUnlocked(*ptr)
```

That preserved instruction shape and gave MWCC the target physical-register
assignment for the pair:

```text
IG48: add sorted_base,index   r23 -> r24
IG46: mr copy of IG48         r24 -> r23
```

The important lesson is not "swap pointer names everywhere." The useful rule is:
when a force proof shows a tiny pairwise allocator swap between an implicit
`add base,index` temp and a copied scan pointer, try changing which source
pointer name owns the initial base+index expression and which owns the copy.

## Baseline and retained frontiers

The useful checkpoints were:

| Checkpoint | Result | Why it mattered |
|---|---:|---|
| `baseline-checkdiff.json` | 99.57071%, opcode-perfect, 10 hunks | Still several register-allocation symptoms. |
| `current-after-issues.checkdiff.json` | 99.77273%, opcode-perfect, 4 hunks | Earlier helper/inline work had removed most noise. |
| `hand-inline-result-s32.checkdiff.json` | 99.79798%, opcode-perfect, 6 hunks | Hand-inlining the down-name helper moved the right direction. |
| `partial-namecount-frontier.checkdiff.json` | 99.79798%, opcode-perfect, 4 hunks | Adding a separate `name_count` fixed the down-name pressure while preserving structure. |
| `manual-owner-flip.checkdiff.json` | 100.0%, instruction-identical | Pointer-ownership flip fixed the last down-fighter pair. |

The retained source before the final fix had exactly one meaningful residual:

```diff
- add r24,r31,r22
+ add r23,r31,r22
...
- mr r23,r24
+ mr r24,r23
...
- lbz r3,0(r23)
+ lbz r3,0(r24)
```

## Tools that gave the right signals

### `checkdiff.py`

`tools/checkdiff.py mnDiagram_UpdateScrollArrows --format json` established that
the retained frontier was opcode-perfect:

```text
fuzzy_match_percent: 99.79798
opcode_similarity: 1.0
line_delta: 0
hunk_count: 4
classification: register-allocation
```

That was the gate to stop changing control flow and focus on allocator inputs.

### `debug target force-phys-from-diff`

After a fresh pcdump:

```bash
melee-agent debug dump local src/melee/mn/mndiagram.c \
  --function mnDiagram_UpdateScrollArrows \
  --output build/mndiagram-scroll-follow/post-1169-1170.pcdump.txt
```

the force target command derived:

```bash
melee-agent debug target force-phys-from-diff \
  build/mndiagram-scroll-follow/post-1169-1170.pcdump.txt \
  -f mnDiagram_UpdateScrollArrows \
  --checkdiff-json build/mndiagram-scroll-follow/post-1169-1170-sanity.checkdiff.json \
  --verify --json
```

Key result:

```text
force_phys_csv: 0:48:24,0:46:23
union: match
singletons: no_match
```

This proved the remaining mismatch was exactly a coupled two-node assignment.
Forcing both nodes matched the function byte-for-byte; forcing either one alone
did not.

### `debug inspect first-divergence`

The first-divergence analyzer identified the first target failure:

```text
class 0, iter 48, ig_idx 48
baseline: r23
target:   r24
case: B
first def: B81: add r48,r71,r54
source kind: implicit-temp
source expression: add r48,r71,r54
```

The useful source hint was:

```text
implicit address temp: preserve implicit indexed array expressions; try
same-line index/base expression spelling, index-local scope, or
indexed-pointer-loop variants that keep the address temp implicit
```

The negative hint also mattered:

```text
reject materialized element pointers such as candidate = &array[index]
reject split base-plus-increment pointer walks
```

This ruled out a lot of tempting but structurally noisy pointer rewrites.

### `debug suggest register-tiebreak`

The surrogate solver reported the abstract repair:

```text
target: {48 -> r24, 46 -> r23}
best perturbation: move IG46 before IG48
source object for IG46: mr r46,r48
source object for IG48: add r48,r37,r54
```

That reframed the source question: not "change the loop," but "make the copied
scan pointer and the base+index pointer swap source ownership."

### `debug select-order-search`

The targeted source-family run:

```bash
melee-agent debug select-order-search \
  -f mnDiagram_UpdateScrollArrows \
  --target 'r46<r48' \
  --pcdump build/mndiagram-scroll-follow/post-1169-1170.pcdump.txt \
  --source-file src/melee/mn/mndiagram.c \
  --include-transform-corpus \
  --transform-family indexed_byte_address_temp_steering \
  --force-phys '48:24,46:23' \
  --beam-depth 1 \
  --beam-width 6
```

did not find a keeper, but its failure was useful:

```text
status: blocked
terminal_blocker: transform-family-exhausted
force-phys-hit-46: 3
force-phys-hit-48: 0
next_source_lever_classes:
  - manual-subhunk-recombine
  - target-aware-live-range-anchor
  - target-aware-interference-shape
```

Some bad candidates could make `IG46` hit r23, but they pushed `IG48` down to
r22 and broke opcode/frame shape. The campaign also spent its ranked indexed-byte
budget on earlier `data->jobjs[...]` accesses, while the real source object was
the down-fighter `sorted + i` address temp. That pointed at a hand-written
subhunk change instead of another broad transform run.

## Misleading signals we rejected

### Superficial score improvement

Changing only pointer increment source order improved the visible score to about
99.89899%, but the force-vector union no longer matched. That meant the candidate
was moving the observed diff while losing the proven allocator target. It was
rejected as a local maximum.

### Direct helper call extraction

Replacing the down-fighter inline scan with a helper call changed the frame and
instruction shape. That confirmed the last residual was not "make the source more
abstract"; it needed the same inline scan shape with different temporary ownership.

### Generic source-family probes

Declaration-order, type-width, block-scope, guard-return, and indexed-byte source
families either no-oped or produced structural drift. The terminal summaries were
still valuable because they distinguished "no progress" from "one target hit but
wrong companion allocation."

## Final source move

The winning manual change was intentionally small:

```c
count = 7;
i = data->fighter_cursor_pos >> 8;
ptr2 = sorted + i;
do {
    if (count == 0) {
        result2 = sorted[i];
        break;
    }
    ptr = ptr2;
    do {
        i++;
        ptr++;
        ptr2++;
        if (i >= 0x19) {
            result2 = 0x19;
            goto dn_fc_done;
        }
    } while (mn_IsFighterUnlocked(*ptr) == 0);
    count--;
} while (count >= 0);
```

This changed which source name owned the implicit `sorted + i` temp and which
source name owned the `mr` copy, without changing the loop's control-flow shape.

## Applicability to the rest of `mndiagram.c`

After the match, the current TU had six non-100% functions:

| Function | Match | Current classification | Applicability of this lesson |
|---|---:|---|---|
| `mnDiagram_InputProc` | 98.82675% | instruction-sequence | Contains similar visible-entry scans, but force-vector union has 11 targets and does not match. Not a direct two-node ownership case. |
| `mnDiagram_CreatePopupTexts` | 99.47293% | instruction-sequence | Early prologue/instruction-order residual, not this pattern. |
| `mnDiagram_DrawCellValue` | 99.88327% | normalized structural match | FPR/constant-label/register reuse issue, not this pointer ownership pattern. |
| `mnDiagram_DrawGridValues` | 96.42216% | normalized structural near-match | Uses `GetVisibleNameCursorFrom`/`GetVisibleFighterCursorFrom2`; likely broader helper-inline and lifetime shape, not a final two-node swap yet. |
| `mnDiagram_DrawNameHeaders` | 98.844444% | stack-layout / structural | Uses `GetVisibleNameFrom`; likely helper-inline/lifetime shape, not proven as the final pointer-ownership pattern. |
| `mnDiagram_DrawFighterHeaders` | 98.10861% | normalized structural near-match | Has the closest source resemblance, but force-vector union has 9 targets and does not match. Direct ownership flip worsened to 97.883896 and 17 hunks. |

The reusable diagnostic sequence is:

1. First get to an opcode-perfect or near-perfect frontier.
2. Run `force-phys-from-diff --verify`.
3. Only apply this ownership flip when the force proof is a small coupled pair
   where one node is an implicit `add base,index` temp and the other is its
   copied scan pointer.
4. If the force union does not match, treat the pattern as a clue only; solve the
   broader source shape first.

`melee-agent patterns inlines src/melee/mn/mndiagram.c` still flags the visible
helper family:

```text
mnDiagram_GetVisibleNameFrom            lines 1210, 1214, 2108, 2561, 2589
mnDiagram_GetVisibleNameCursorFrom      lines 2451, 2477, 2484
mnDiagram_GetVisibleFighterCursorFrom2  lines 2460, 2508, 2515
```

That supports the earlier suspicion that helper-inline shape remains important
elsewhere in the TU. The `UpdateScrollArrows` result narrows the next work: do
not blindly rewrite all helpers; first prove whether each function's residual is
a forceable allocator pair or a broader helper/control-flow source shape.
