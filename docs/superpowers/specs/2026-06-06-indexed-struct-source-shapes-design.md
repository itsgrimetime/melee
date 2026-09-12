# Indexed-Struct Source Shapes Design

Date: 2026-06-06
Status: Implemented and verified
Issue: #452

## Problem

`indexed-struct-search` reports `indexed-struct-hint-unavailable` for several
rows where `checkdiff` already exposes indexed-pointer materialization evidence.
The source scanner only understands two source shapes:

- materialized struct pointers declared as `T* p = &base[i]` or `T* p = base + i`
- repeated direct field reads like `base[i].field`

The reported functions use related but unsupported forms:

- `hsd_80391AC8`: separated pointer declaration plus casted pointer-plus
  assignment, `u8* p; ... p = (u8*) (str + i)`, followed by `p[n]`
- `it_80294364`: single-use direct indexed struct fields such as
  `attr->x28_entries[picked].x0_anim_joint`
- `mnItemSw_802351A0`: direct indexed pointer-array elements passed into
  calls, such as `data->jobjs[5]`

Because none of these shapes produce source candidates, the harvest lane cannot
distinguish "unsupported but source-actionable" from "no source lever".

## Goals

1. Generate source candidates for safe casted pointer-plus array uses.
2. Generate source candidates for safe single-use direct indexed field reads.
3. Generate source candidates for safe direct indexed element reads.
4. Preserve existing safety constraints: no lvalue rewrites, no address-taken
   rewrites, no preprocessor-spanning rewrites, and no mutation of base/index
   expressions before the rewritten use.
5. Keep unsupported rows explicit by reporting supported/rejected/safe counts
   instead of leaving generic `indexed-struct-hint-unavailable` when the source
   scanner found a recognizable but unsafe shape.

## Non-Goals

- Do not try to infer full struct layouts.
- Do not edit Melee source functions as part of this tooling fix.
- Do not guarantee that every generated probe matches. The harness already
  compiles/scores candidates and records no-match evidence.
- Do not rewrite lvalue direct indexed expressions such as `base[i].field = x`.

## Design

Extend `tools/melee-agent/src/mwcc_debug/pressure_explorer.py` inside the
existing indexed-struct scanner.

### Casted Pointer-Plus Array Uses

Teach `_parse_indexed_struct_pointer_initializer()` to unwrap simple casts and
outer parentheses around plus expressions, for example `(u8*) (str + i)`.
Extend candidate discovery to support both initialized declarations and
separated assignment shapes:

```c
u8* p;
p = (u8*) (str + i);
```

The candidate span for assignment shapes starts at the assignment statement, not
the earlier declaration, so the probe removes only the redundant assignment and
leaves the declaration intact. Extend pointer-use scanning with an
`array-subscript` mode that recognizes standalone `p[n]` reads after such
declarations or assignments and rewrites them to `((u8*) (str + i))[n]`. The
scanner must reject `p[n]` lvalues, address-taken `p[n]` uses, and any remaining
pointer token outside the rewritten subscripts.

### Single-Use Direct Field Splits

The current direct field splitter requires at least two uses of the same
`base[index].field` expression before it generates a scalar split. For
`indexed-struct-pointer-materialization`, a single safe direct indexed field can
be source-actionable. Relax the minimum to one safe use and keep the existing
mutation, lvalue, address-taken, and preprocessor guards. Improve scalar type
inference so pointer-returning functions and return statements can split
pointer fields safely. For `HSD_AnimJoint* fn(...) { return
attr->entries[picked].anim; }`, infer `HSD_AnimJoint*`; if no contextual type is
available and the expression is used as a pointer-looking call argument, use
`void*` rather than `f32`. Otherwise reject the candidate.

### Direct Indexed Element Splits

Add a sibling scanner for direct indexed element reads with no trailing field,
for example `data->jobjs[5]`. It should use the same safety checks as direct
field splits, skip lvalues and address-taken expressions, and generate one
scalar local for the first safe use. Type inference is intentionally small:
if the expression shape is `base->field[index]` or `base.field[index]`, look up
the base variable type in scoped local/parameter declarations and then scan the
current source text for that struct field declaration. For `MnItemSwData* data`
and visible `HSD_JObj* jobjs[9]`, infer `HSD_JObj*`. The real
`mnItemSw_802351A0` field type lives in a header that the scanner does not
currently read, so direct indexed elements used as function arguments may fall
back to `void*` when no visible field declaration is available. Otherwise reject
the candidate so the row gets a concrete unsupported-source-shape blocker.

## Acceptance

- `scan_indexed_struct_pointer_probes()` returns at least one safe probe for a
  separated casted pointer-plus assignment followed by `p[n]` reads.
- `p[n]` lvalues and address-taken uses are rejected.
- It returns at least one safe probe for a single direct indexed field read.
- Pointer-returning functions split pointer fields with a pointer-compatible
  scalar type.
- It returns at least one safe probe for a direct indexed pointer-array element
  read where the element type can be inferred from a visible struct typedef, and
  also for call-argument pointer-array elements where only `void*` is safe.
- The three reported functions produce probes in no-compile CLI mode instead
  of `indexed-struct-hint-unavailable`.
- Existing rejection tests for escaped pointers, mutations, address-taken
  expressions, comments, strings, and preprocessor regions still pass.
- Parenthesized lvalue forms such as `(p[n]) = x`, `++(p[n])`, and
  `(base->field[n])++` are rejected.
- Control and `sizeof` contexts with comments or line breaks are rejected for
  direct indexed element splits.
