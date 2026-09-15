# Loop-Shape Expanded Structure Axis Design

## Context

Issue #509 reports that `debug search structure` still leaves a
`loop-shape-expanded` future axis for the MN sorted-list scan loops in:

- `mnDiagram_802427B4`
- `mnDiagram_80242C0C`
- `mnDiagram_8024227C`
- `mnDiagram_802417D0`

The immediate failure mode is a visible-entry scan over a sorted MN list. The
source appears in several spellings:

- direct asset fields such as `assets->sorted_names` and
  `assets->sorted_fighters`;
- file-global fields such as `mnDiagram_804A0750.sorted_fighters`;
- local aliases such as `u8* sorted = mnDiagram_804A0750.sorted_fighters`,
  including the name-mode `sorted + 0x1C` offset used by
  `mnDiagram_802417D0`.

Current source keeps manual `idx`, `remaining`, `p`, and `p2` lifetimes with a
predicate call such as `GetNameText(*p2) == NULL` or
`mn_IsFighterUnlocked(*p2) == 0`. The largest reported function,
`mnDiagram_8024227C`, uses register-var names and goto labels instead of clean
structured loops. Matching agents need bounded, retained source candidates that
vary these loop shapes before they declare a backend/register ceiling.

## Goals

- Add `loop-shape-expanded` as a supported source-based structure-search axis.
- Generate retained candidate `.c` files for sorted visible-entry scan loops.
- Cover helper-vs-direct loop shape, while-condition spelling, pointer/index
  lifetime, final offset load form, and predicate placement.
- Reuse existing structure-search ranking and scoring; the new axis only
  generates candidates.
- Keep the working tree read-only. All candidate changes are written under the
  structure-search output directory.

## Non-Goals

- Do not solve the MN matches directly.
- Do not build a general C loop refactoring engine.
- Do not rewrite arbitrary loops without the sorted-list and predicate-call
  evidence.
- Do not apply generated candidates to production C.

## Design

Add a source-based optional axis in `tools/melee-agent/src/search/structure.py`.
The axis locates the requested function, rejects preprocessor directives inside
the function body, then scans for bounded MN sorted-list patterns:

- a sorted list expression containing `sorted_names` or `sorted_fighters`;
- a visibility predicate call, either `GetNameText(...)` or
  `mn_IsFighterUnlocked(...)`;
- an index variable assigned from a cursor argument;
- a remaining/skip counter;
- pointer variables commonly named `p` and `p2`, plus register-var aliases
  such as `var_r16`, `var_r17`, or `var_r15_2`;
- a final assignment from the same sorted list into a result byte such as
  `name_id`, `fighter_id`, `var_r0`, or `result2`.

Detection must produce candidates for all four issue functions, not only a
synthetic clean loop. In particular:

- `mnDiagram_802417D0` must be covered through its local `sorted` alias and
  `sorted + 0x1C` offset name-mode scan.
- `mnDiagram_8024227C` must be covered through goto-heavy register-var scan
  shapes such as `loop_7`, `loop_29`, `loop_48`, and `loop_87`.

Each detected scan emits candidates in per-scan, per-family order so a small
`--max-candidates` value does not starve later families in functions with many
eligible scans. The retained families are:

- `loop-shape-expanded-direct-index`: remove the `p`/`p2` cursor aliases inside
  the scan and use `assets->sorted_*[idx]` directly in the predicate and final
  load.
- `loop-shape-expanded-base-pointer`: keep one base pointer to the sorted list
  and index through that base, delaying base plus cursor materialization until
  after the count guard.
- `loop-shape-expanded-predicate-temp`: materialize the visibility predicate
  result in a C89-safe local block before the branch.
- `loop-shape-expanded-inverted-predicate`: spell the predicate as a positive
  visible test with an `else goto` branch, preserving control flow but changing
  branch shape.
- `loop-shape-expanded-helper`: insert a file-local `static inline u8` helper immediately
  before the target function and replace a bounded scan statement group with a
  helper call when the span can be isolated safely. If the scan is too
  label-heavy to replace safely, emit the other source-shape variants and record
  the helper blocker in axis metadata instead of forcing an unsafe helper.

The generator records metadata for each variant:

- `family`
- nested `scan` details with source kind, list kind, predicate, source
  expression, index expression, original predicate expression, and clean-span
  status
- family-specific fields such as replacement expression, helper name, base
  argument, remaining variable, limit, or predicate temporary
- touched source lines
- source diff

`run_structure_search` wires the axis like other source-based axes. If the axis
is implemented, `structure_payload(...)[\"future_axes\"]` no longer lists
`loop-shape-expanded`.

## Safety

- Operate only inside the located target function body.
- Reject functions with preprocessor directives in the body.
- Generate variants only when the scan has both sorted-list evidence and a
  known visibility predicate.
- Use existing masking helpers to avoid matching comments and string literals.
- Insert helper functions before the target function only, mirroring existing
  inline-boundary helper insertion behavior.
- Deduplicate candidate source text before writing files.

## Testing

Add regression tests for:

- `generate_loop_shape_expanded_variants` producing direct-index, base-pointer,
  predicate-temp, inverted-predicate, and helper candidates for a
  `GetNameText` sorted-name scan.
- The same axis producing variants for an `mn_IsFighterUnlocked` sorted-fighter
  scan.
- Fixture-style source snippets from all four issue functions:
  `mnDiagram_802427B4`, `mnDiagram_80242C0C`, `mnDiagram_8024227C`, and
  `mnDiagram_802417D0`. The `802417D0` snippet must include the local `sorted`
  alias plus `+ 0x1C`; the `8024227C` snippet must include goto labels and
  register-var names.
- `run_structure_search(..., axes=(\"loop-shape-expanded\",))` returning an
  evaluated axis, retained source paths, and no `loop-shape-expanded` future
  axis marker.
- Rejection of unsafe sources with preprocessor directives or no sorted-list
  predicate evidence.
- CLI smoke for `melee-agent debug search structure -f mnDiagram_802427B4
  --axis loop-shape-expanded --no-score --json` returning at least one retained
  source variant when live source is available.
