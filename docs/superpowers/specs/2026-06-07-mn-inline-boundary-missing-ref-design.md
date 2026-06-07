# MN Inline Boundary Missing-Reference Design

## Context

Issue #505 reports that `debug search structure --axis inline-boundary` returns
`no-inline-boundary-candidates` for several `mn` functions whose checkdiff
classification mentions missing reference calls or inline-boundary guidance:

- `mnDiagram_8023FC28`
- `mnDiagram_80240D94`
- `mnDiagram_8024227C`
- `mnDiagram_802427B4`
- `mnDiagram2_GetAggregatedFighterRank`

The existing inline-boundary axis already emits fake axis-setter wrappers,
call-argument temporaries, user-data casts, and SisLib cleanup helpers. These
families do not match the reported sources. The affected functions mostly show
three source shapes:

- calls used directly inside conditions or field/member expressions, such as
  `GetNameText(...) != NULL` and `GetPersistentNameData(...)->field`;
- repeated popup text setup blocks around `HSD_SisLib_803A6754`,
  `lb_8000B1CC`, font/position assignments, and text formatting calls;
- local sort-entry array initialization before a ranked aggregation loop.

The issue also notes that some checkdiff "missing reference call" rows are
shifted same-target call sequences. The tool should expose that distinction so
agents do not chase helper extraction when the evidence points to earlier
address-materialization, lifetime, or frame alignment.

## Approaches Considered

1. **Focused inline-boundary families in `search.structure`.** Add small,
   source-retained generators for the three observed `mn` shapes and add
   missing-reference metadata to the axis summary. This is recommended because
   it reuses existing candidate retention/scoring and directly removes the
   zero-candidate blocker.
2. **Generic helper extraction for arbitrary statement ranges.** This could
   cover more future cases, but safely inferring helper signatures, parameter
   lists, and return values is too broad for this queue item.
3. **Diagnostic-only rebucketing.** Distinguishing shifted same-target rows is
   useful, but advisory metadata alone would leave the reported source-action
   request unresolved.

## Design

### Call-Result Temporaries

Add an `inline-boundary-call-result-temp` family that rewrites a single simple
call expression into a local temporary when the call is used as a subexpression.
The first implementation supports a bounded allowlist of MN helper return
types:

- `GetNameText(...)` -> `char*`
- `GetPersistentNameData(...)` -> `struct NameTagData*`
- `GetPersistentFighterData(...)` -> `struct FighterData*`
- `mnDiagram_GetFighterByIndex(...)` -> `u8`

Examples:

```c
if (GetNameText((u8) j) != NULL) {
```

becomes a candidate source block:

```c
{
    char* ib_probe_call_result_0 = GetNameText((u8) j);
    if (ib_probe_call_result_0 != NULL) {
        ...
    }
}
```

and:

```c
total += GetPersistentNameData((u8) i)->vs_kos[(u8) j];
```

becomes:

```c
{
    struct NameTagData* ib_probe_call_result_0 =
        GetPersistentNameData((u8) i);
    total += ib_probe_call_result_0->vs_kos[(u8) j];
}
```

The generator rewrites one call occurrence per candidate but rewrites the full
owning statement span, not just one line. For an `if`/`while` condition, the
span is the full statement including the braced body or single controlled
statement, so the wrapper block can insert the local declaration before the
condition and close after the controlled statement. For expression statements,
the span ends at the top-level semicolon. The implementation must use masked
source and brace/paren matching helpers so multiline conditions such as
`if ((GetNameText(a) != NULL) && ...)` remain valid C. Declaration lines,
assignment left-hand sides, and macro/preprocessor regions are skipped. Each
variant records callee, return type, source line, original expression,
replacement variable, and statement span in metadata.

### Popup Text Setup Helper

Add an `inline-boundary-popup-text-setup-helper` family for the repeated
`mnDiagram_80240D94` text setup shape:

1. create text with `HSD_SisLib_803A6754(0, 1)`;
2. store it into `data->text[index]`;
3. call `lb_8000B1CC(data->jobjs[index], &tbl->points[index], &pos)`;
4. assign font size, position from `pos`, and alignment.

For each matched block, insert a file-local `static inline HSD_Text*` helper
immediately before the target function and replace the block with a helper call
that returns `text`. The helper takes the target data pointer, animation table,
position pointer, text slot, jobj slot, point slot, font sizes, and alignment.
This is intentionally specific to the popup setup pattern; it does not attempt
general statement outlining.

### Popup Number Formatting Helper

Add an `inline-boundary-popup-number-format-helper` family for the numeric
formatting blocks in `mnDiagram_80240D94`. It targets the repeated source shape:

1. choose a numeric value from `GetPersistentNameData(...)->field` or
   `GetPersistentFighterData(...)->field`;
2. call `mnDiagram_IntToStr(buf, value)`;
3. pass `buf` to `HSD_SisLib_803A6B98(text, 0.0f, 0.0f, buf)`.

The candidate inserts a file-local `static inline void` helper before the target
function and replaces the matched formatting statement group with a helper call.
The helper receives the text object, `buf`, the selected value, and preserves
the `mnDiagram_IntToStr` plus `HSD_SisLib_803A6B98` call order. This explicitly
covers the popup number-formatting wrapper requested by #505 without extracting
arbitrary popup control flow.

### Sort Entry Initialization Helper

Add an `inline-boundary-sort-entry-init-helper` family for
`mnDiagram2_GetAggregatedFighterRank`-style initialization:

```c
do {
    ptr->name = mnDiagram_GetFighterByIndex(i);
    i++;
    ptr->xC = zero;
    ptr->x8 = zero;
    ptr++;
} while (i < 25);
```

The candidate inserts a file-local static inline helper before the target
function and replaces the initialization loop with a helper call. The helper
receives the entry array and zero value, preserves the loop order, and uses the
same `mnDiagram2_SortEntry` type as the source.

### Missing-Reference Metadata

Add optional baseline classification plumbing to `run_structure_search`.
The CLI path already computes a baseline checkdiff payload when scoring
variants; this feature threads the baseline payload or its `classification`
into `generate_inline_boundary_variants`. Unit tests can pass the classification
directly. No candidate scorer behavior depends on this metadata.

When a baseline classification contains `inline_boundary_artifact`, add
`inline_boundary_artifact` metadata to the inline-boundary axis summary:

- count of reported `missing_ref_calls`;
- count of call offsets whose relocation targets appear to be same-function
  shifted rows, based on same-function offset markers such as
  `<mnDiagram_8023FC28+0x3c>`;
- a `source_lever_classification` of `true-missing-reference-calls`,
  `shifted-same-target-calls`, or `mixed`.

This metadata does not block candidate generation. It explains whether agents
should prioritize helper/call-boundary candidates or pivot to
address-materialization/lifetime/frame alignment after bounded variants fail.

## Safety

- All variants are retained source files only; the working tree is not mutated.
- Generators operate inside a located target function, except for one
  file-local static inline helper inserted immediately before that function.
- The axis already rejects target functions with preprocessor directives in the
  body; these new families use the same guard.
- Call-result temp variants only use an explicit allowlist of return types.
- Helper extraction is pattern-specific and does not infer arbitrary
  signatures.

## Testing

Add regression tests for:

- call-result temp candidates for `GetNameText` conditions and
  `GetPersistentNameData(...)->field` member access, including multiline
  `if` statements whose whole statement span is wrapped;
- popup text setup helper candidate source and metadata;
- popup number-formatting helper candidate source and metadata;
- sort-entry initialization helper candidate source and metadata;
- inline-boundary axis summary metadata derived from a baseline
  `inline_boundary_artifact` classification;
- `run_structure_search(..., axes=("inline-boundary",))` producing retained
  variants for fixtures matching the reported `mn` shapes instead of
  `no-inline-boundary-candidates`;
- command-level smokes for the reported functions showing at least one
  inline-boundary candidate and scored/retained source files where compilation
  succeeds.

## Out of Scope

- Generic arbitrary helper extraction.
- Applying candidates to production C source.
- Solving the underlying decomp matches for the reported functions.
- Reclassifying every checkdiff inline-boundary artifact; this feature only
  adds metadata needed by structure search.
