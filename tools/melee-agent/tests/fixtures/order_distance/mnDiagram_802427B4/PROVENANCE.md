# Kill-switch fixtures — provenance

## Witness 1: mnDiagram_802427B4
- `pre_win.c` — `src/melee/mn/mndiagram.c` @ `a527c0227~1` (f2d654331), 95.68%.
- `win.c`     — @ `a527c0227` (97.96%; comma-expr LICM defeat:
  `pos.y = (0, mnDiagram_804DBFAC) - HSD_JObjGetTranslationY(j);` + split
  base-pointer `p = sorted; p = p + start;`; stmw r20/12-saves → r21/11-saves —
  the §6c eligibility risk).
- `negative_control.c` — NOT generated: the frozen pre-win source does not
  compile against the current repo tree, so no base match% / control could be
  measured (the negative-control step is downstream of the base build).
- Derivation on the pre-win base routed: **unstable_target**
  (not derivation-eligible — `pre_win_source_does_not_compile_against_HEAD`).
  The frozen pre-win `.c` references the bare identifier `mnDiagram_804DBF84`,
  which was declared in the contemporaneous `src/melee/mn/mndiagram.static.h`
  at `a527c0227~1` but no longer has a C declaration at master HEAD (the win +
  later restructures replaced those raw `mnDiagram_804DBF8x` references with
  named struct fields / float literals and rewrote the static header).
  Verbatim build error captured in `eligibility.json`:
  `undefined identifier 'mnDiagram_804DBF84'` (src\melee\mn\mndiagram.c:1681).
  This is the §6c eligibility risk in its STRONGEST form: not merely a
  callee-save-count change that might push the base out of the order-distance
  class, but a frozen source that will not build against HEAD at all. Freezing
  only the historical `.c` (per the plan's extraction) does not capture the
  contemporaneous header it depends on.
- named_pair: not derived (routing non-directed).

## Witness 2: fn_803ACD58 (cardstate decl-chain; §6c contingency + secondary witness)
- `pre_win.c` = chain step 0 (`ffad1f5ed~1`); `win.c` = step 1 (`ffad1f5ed`,
  decl swap hdr_plus_icon/i, 98.9→99.4); `chain_2.c` (`f2cf55b2b`, retries
  hoist, →99.5); `chain_3.c` (`b7013dc48`, size/retries swap, →99.7). Each a
  one-line decl-order edit — pure order moves on a stable node set.
- `negative_control.c` — pre_win + icon_size/hdr_plus_icon swap; freeze-time
  match% = **98.644066** (≤ base 98.94068 — verified non-improving, assertion
  (d) satisfied).
- Derivation on chain step 0 routed: **not_order_class**.
  The cardstate base's checkdiff primary is `normalized-structural-match`
  (the diff is structurally zero after masking registers/immediates/labels/
  relocations — pure coloring/presentation), which is NOT register-only
  (`{backend-ceiling, operand-register-or-offset}`). The order-distance
  classifier's Step-1 precondition deliberately rejects it: a decl-order win
  whose baseline diff normalizes to structurally identical is INVISIBLE to the
  order-distance metric's pool. Verified stable across 3 builds (primary +
  98.941% identical every time — a reproduced classifier verdict, not noise).

## Gating decision (eligibility.json)
- gating_fixture = **null**.
- BOTH witnesses routed non-directed:
  - `mnDiagram_802427B4` → `unstable_target` (pre-win source does not compile
    against HEAD; not derivation-eligible).
  - `fn_803ACD58` → `not_order_class` (normalized-structural-match is out of
    the order-distance pool).
- Per §6c: with NO derivation-eligible witness, the kill switch **hard-stops at
  T7 with an orchestrator report** — never a silent pass. The orchestrator must
  revisit the kill-switch function assignment (e.g. freeze a witness whose
  pre-win source builds against HEAD and whose baseline diff classifies as a
  register-only `backend-ceiling` / `operand-register-or-offset` mismatch — the
  only primaries the order-distance derivation accepts).

Regenerate everything with: `cd tools/melee-agent && python tests/fixtures/order_distance/generate.py`
