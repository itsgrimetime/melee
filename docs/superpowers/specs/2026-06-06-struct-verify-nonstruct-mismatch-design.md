# Struct Verify Non-Struct Mismatch Design

Date: 2026-06-06
Status: Implementing after independent Codex review
Issue: #460

## Problem

`melee-agent struct verify` reports THP row decoder differences as
`unresolved mismatched bases ... missing dataflow proof`. In the reported THP
cases, the raw checkdiff rows compare reference registers that hold one source
shape against current registers that hold another source shape, such as an MCU
buffer array base or direct `__THPInfo`-derived temporary. These rows are not
actionable THPFileInfo layout findings, but the current skip reason makes them
look like a dataflow feature gap.

## Goal

When struct verify cannot prove a shared base for mismatched registers, classify
rows as explicit `non-struct-source-shape` skips when their displacements do not
look like a plausible same-struct field-layout mismatch.

## Non-Goals

- Do not infer a new alias between implicit `arg3`, `__THPInfo`, and unrelated
  BSS array bases.
- Do not emit struct findings for THP row decoder buffer-array rows.
- Do not change checkdiff.

## Design

Add a helper in `tools/melee-agent/src/cli/struct.py` that inspects an
unresolved mismatched-base row against the selected struct layout:

- compute current and reference displacements from `cur_disp` and `ref_disp`
- map each displacement to a named field with `_offset_to_field()`
- if the current displacement has no named field, return a
  `non-struct-source-shape` reason
- if current and reference map to different named fields, return a
  `non-struct-source-shape` reason
- if only the current displacement maps to a named field but the reference
  displacement is far away from it (more than `0x20` bytes), return a
  `non-struct-source-shape` reason
- if an explicit current base offset makes `base_offset + cur_disp` map to a
  named field, keep the existing unresolved skip instead of classifying the row
  as non-struct
- otherwise keep the existing unresolved dataflow-proof skip

This preserves conservative behavior for nearby offset shifts that might become
field-layout findings once dataflow improves, while making THP’s unrelated BSS
array/global-source rows explicit non-struct classifications.

For ambiguous same-base fallback rows, keep the existing ambiguity unless every
ambiguous candidate independently classifies as `non-struct-source-shape`.
Before converting the ambiguity, run the existing layout-fit inference per
candidate base and preserve `ambiguous offset base candidates` if any candidate
has an explicit, exact, or unique inferred interior base that maps its current
offsets to named fields with nearby adjusted reference displacements or any
adjusted reference displacement that also maps to a named field. Ambiguous
layout-fit candidates are too weak to preserve an already ambiguous base choice.
This lets the THP whole-TU command distinguish global/pointer byte-load source
shapes from base-selection ambiguity without hiding plausible struct rows.

## Acceptance

- `__THPDecompressiMCURow640x480` with `--struct THPFileInfo` and no `--base`
  produces no `missing dataflow proof` skip.
- `__THPDecompressiMCURowNxN` with `--struct THPFileInfo` and no `--base`
  produces no `missing dataflow proof` skip.
- Existing same-root dataflow findings and nearby unresolved rows remain
  unchanged.
- Unit tests cover unnamed-current, far named-current, different named fields,
  nearby named-current behavior, explicit base-offset preservation, and fully
  non-struct ambiguous fallback behavior, including inferable interior-base
  ambiguity preservation.
