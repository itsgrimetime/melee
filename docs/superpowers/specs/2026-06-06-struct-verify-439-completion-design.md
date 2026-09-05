# struct verify #439 completion - dataflow bases and guarded layout repair

Date: 2026-06-06
Status: automation-approved via issue #439; independent Codex review required
Issue: #439

## Problem

`struct verify` v1 required explicit per-function base registers. The v2 partial
work can infer a base when `checkdiff` reports exactly one offset-discrepancy
base, normalize explicit interior offsets, and apply one positive padding edit.
That is not enough for #439. Matching agents still hit functions where the
source struct pointer is copied to a callee-save, cast through an `addi reg,arg,0`
shape, or used through an interior pointer derived from a base register. They
also need an apply path that can repair simple byte layouts, not just insert
new padding before one field.

## Goals

1. Infer per-discrepancy base evidence from the built assembly using a small,
   local dataflow model: argument roots, `mr`, `addi reg,base,imm`, and simple
   global pointer loads.
2. Normalize top-level and constant interior-pointer discrepancies before field
   lookup. Dynamic interiors may still fall back to the existing unique
   layout-fit heuristic, but ambiguous cases must report candidates rather than
   fabricate a finding.
3. Extend `--apply` into a guarded layout repair path. It may insert padding,
   shrink/remove an immediately preceding pad array, or move a single top-level
   declaration only when the edited header passes `struct_layout.verify_offsets`.
4. Preserve the existing explicit `--base`, `--base-map`, `--base-offset`, and
   report-only behavior.

## Non-Goals

- Full control-flow-sensitive alias analysis.
- Reconstructing arbitrary C layouts from scratch.
- Applying nested field edits or multi-field conflicting repairs in one pass.
- Treating heuristic evidence as success without an `offsetof` verification.

## Design

### Assembly Evidence

Add pure helpers in `tools/melee-agent/src/cli/struct.py` near the existing
`struct verify` helpers, and enrich `tools/checkdiff.py` rows so alias cases are
not lost before `struct verify` sees them:

- Resolve the assembly file from `--tu-src` by mapping common source roots to
  `build/GALE01/asm/...` and falling back to a basename search.
- Extract a `.fn NAME` to `.endfn NAME` block.
- Scan instructions in order and track `RegisterTrace(root, offset, source)`.
  Initial roots are `arg3` through `arg10`. `mr dst,src` copies the trace.
  `addi dst,src,imm` copies the trace with a constant offset. `lwz dst,
  symbol@sda21(r13)` creates a `global:symbol` trace. Writes to a destination
  register without a modeled source invalidate the previous trace.
- `checkdiff` continues emitting the existing `base_reg`, `cur_disp`, and
  `ref_disp` fields, but also includes `ref_base_reg`, `cur_base_reg`,
  instruction-only `ref_index`, and instruction-only `cur_index`. Rows with
  differing physical bases are allowed when mnemonic and displacement shape
  match, so `struct verify` can canonicalize through access-position dataflow.
  The JSON `target_asm` and `current_asm` arrays are parsed separately so
  reference-side bases are proven from reference-side instructions rather than
  from the current object.

The command uses this evidence only to explain registers that already appear in
`classification.offset_discrepancies`; it does not invent findings.

### Base Selection

Explicit user inputs still win for current-side base selection. Without
explicit inputs, the command resolves each discrepancy row independently:

- If all usable discrepancy bases trace to one root at their respective
  reference/current access indices, keep all rows for that root and use each
  row's traced constant current-side offset as `base_offset`.
- If a row's register has no trace and the reference/current physical bases are
  the same, fall back to the existing unique physical-base inference for
  compatibility.
- If reference/current physical bases differ, require dataflow proof for that
  row; otherwise skip it with a concrete reason.
- If multiple roots are present, skip the function with a precise reason.
- If a trace has no constant interior offset, use the existing
  `_infer_base_offset_from_layout` on the rows for that register and include
  ambiguous candidates in `skipped`.

Findings keep the v2 JSON fields and add dataflow-oriented source names such as
`base_reg_source=dataflow:arg3` and `base_offset_source=asm-dataflow`.

### Guarded Apply

Replace the padding-only apply helper with a repair helper that operates on a
single non-conflicting top-level aggregate:

1. Build an affected offset map from the selected field plus every known later
   top-level field in the same struct window for pad insert/shrink candidates.
2. Try inserting positive padding before the field.
3. Try shrinking or removing the immediately preceding pad/unk byte array when
   the expected offset is lower.
4. Try moving the field declaration before the top-level declaration currently
   occupying the expected offset.

Each candidate edit writes the header, calls `struct_layout.verify_offsets` for
the affected offset map, and restores the original header if the candidate
fails. JSON includes the applied strategy or a concrete `not_applicable` reason.

## Testing

- Pure tests for `mr`, `addi reg,arg,0`, constant interior `addi`, global `lwz`,
  alias invalidation on overwrite, call handling, and ambiguous multi-root
  dataflow.
- `checkdiff` integration coverage for paired instructions whose physical bases
  differ but whose rows can still be canonicalized by `struct verify`.
- CLI tests that monkeypatch `checkdiff` and assembly extraction to verify
  no-`--base` alias inference and constant interior normalization.
- Apply tests for positive pad insertion, preceding pad shrink/removal, guarded
  field move, nested/indexed rejection, and restore-on-failed-verification.
- Existing struct-verify and struct-layout tests must keep passing.

## Acceptance

- `melee-agent struct verify <function> --struct TYPE --tu-src TU --json` can
  report findings when the discrepancy base is a copied/cast argument register.
- Constant interior-pointer rows produce top-level field paths and absolute
  offsets without requiring `--base-offset`.
- Ambiguous multi-root or ambiguous dynamic-interior evidence is visible in
  `skipped`.
- `--apply` can perform a verified simple pad insert, pad shrink/removal, or
  top-level field move, and it restores the file when verification fails.
