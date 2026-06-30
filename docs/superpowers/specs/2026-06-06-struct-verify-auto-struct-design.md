# Struct Verify Auto-Struct Design

Date: 2026-06-06
Status: Implemented after independent Codex review
Issue: #456

## Problem

`melee-agent struct verify` can now infer base registers and interior base
offsets, but it still requires `--struct`. For many `struct-offset-discrepancy`
rows, the struct identity is visible in C source rather than in the function
signature: globals such as `lbl_8046DBD8`, `gobj->user_data` aliases, local
aliases of globals such as `THPFileInfo* info = __THPInfo`, second and later
arguments, and helper-return structs such as `gm_8018F634()`.

That requirement forces manual source archaeology before harvest can decide
whether an offset discrepancy is a named field-layout issue or non-actionable
data/global noise.

## Goals

1. Make `--struct` optional for `struct verify`.
2. Infer source-derived struct candidates from the target TU and local include
   files.
3. Auto-select only when exactly one candidate is proven by the existing
   layout/dataflow resolver.
4. Preserve the explicit `--struct` path and its output.
5. Include the selected struct name in JSON findings so later taxonomy gating
   can distinguish real field-layout rows.
6. Update taxonomy next-action commands so struct-offset rows no longer tell
   agents to manually provide `--struct <struct-name>`.

## Non-Goals

- Do not build a full C type checker.
- Do not parse every system include or macro expansion.
- Do not auto-apply repairs when `--struct` was inferred; `--apply` remains
  guarded by the existing aggregate checks.
- Do not classify #455’s taxonomy bucket in this change. This change creates
  the resolver signal that #455 can consume.

## Design

### Candidate Collection

Add a small source identity collector in `tools/melee-agent/src/cli/struct.py`.
It reads the target function body, the TU-level declarations in the source file,
and directly included local headers (`"foo.h"`) that can be resolved next to the
TU or under repository source roots. Header content is used only for declarations
referenced by the target function body, not as a broad pool of unrelated
prototypes. The collector extracts candidate struct names and source roots from
conservative C patterns:

- function parameters and local declarations with pointer-like types, including
  second and later arguments such as `CameraTransformState* state`; parameter
  candidates carry roots such as `arg3`, `arg4`, etc.
- direct casts such as `(Fighter*) gobj->user_data`
- local aliases such as `Fighter* fp = GET_FIGHTER(gobj)` and
  `THPFileInfo* info = __THPInfo`; aliases carry roots derived from their
  initializer, such as `arg3:user_data` or `global:__THPInfo`
- global declarations mentioned by the function body, such as
  `static lbl_8046DBD8_t lbl_8046DBD8`; global candidates carry
  `global:<symbol>` roots
- pointer-returning helper declarations/definitions when the target function
  calls that helper, such as `TmData* gm_8018F634(void)`; helper candidates
  carry `call:<function>` roots

The collector normalizes `struct Foo*` and `Foo*` to `Foo`, filters primitive
types and `void`, preserves evidence strings, and returns candidates in source
order without duplicates.

### Resolver-Proved Selection

When `--struct` is omitted, `struct verify` processes each function with the
same checkdiff rows, asm traces, base maps, and base-offset maps it already
uses. For each candidate struct:

1. Resolve the layout with `struct_layout.resolve_layout(repo, candidate, tu_src)`.
2. Run `_resolve_discrepancy_rows()` with that layout.
3. Convert rows to named-field findings with `_finding_from_offset_discrepancy()`.

The command auto-selects a candidate only when one candidate has named-field
findings and every other candidate has fewer findings. When resolved rows carry
a dataflow root such as `dataflow:arg4` or `dataflow:global:__THPInfo`, the
candidate must carry the same root. For fallback rows resolved by unique
base-register/layout fit, the candidate must still be tied to the target
function body: a parameter, local alias, mentioned global, user-data alias, or
called helper. If no candidate maps to a named field, skip the function with an
explicit `auto-struct unresolved` reason. If two or more candidates tie for the
best mapped findings, skip with `auto-struct ambiguous` and include candidate
names.

This keeps the feature high precision: source hints propose identities, but the
existing struct-layout resolver proves the identity before findings are emitted.

### Output

JSON findings gain a `struct` key when the struct was inferred or explicit.
`tools/melee-agent/src/common/struct_verify.py` changes aggregation to group by
`(struct, field)` when `struct` is present, preserving old behavior for callers
that do not provide struct names. Skips remain `[function, reason]` pairs for
compatibility.

The help text changes from `--struct [required]` to an optional
`--struct Struct type name; inferred from source when omitted`.

## Acceptance

- `struct verify --help` no longer marks `--struct` required.
- With `--struct`, existing struct-verify tests and output still pass.
- Without `--struct`, CLI tests show unique auto-selection for:
  - a second-argument struct parameter
  - a local `gobj->user_data` / `GET_FIGHTER` alias
  - a global/local alias of a static global pointer
  - a helper-return pointer call
- Ambiguous or unmapped candidates produce explicit skip reasons rather than
  arbitrary findings.
- JSON findings include `struct` and aggregate by struct plus field.
- `tools/function_taxonomy_inventory.py` emits `melee-agent struct verify ...`
  without `--struct <struct-name>` for struct-offset next commands.
- Candidate selection tests cover ambiguous equal-score candidates and ensure a
  wrong candidate with matching offsets is rejected when its root does not match
  the resolver root.
