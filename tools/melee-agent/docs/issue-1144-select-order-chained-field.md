# Issue 1144: Select-Order Chained Field-Load Bridge

## Problem

`debug select-order-search` could attribute `fn_802461BC` target IG42 to the
pcode load `lwz r42,40(r263)`, but source probing stopped at
`field-load-base-source-unresolved` when IG263 represented a chained GObj
field load. The source-level shape was `data->popup_gobj->hsd_obj`; the tool
only handled simple local bases like `gobj->user_data`.

## Fix Shape

- Expand select-order source attribution to chase pcode field-load
  `base_virtual` values, bounded to three retry hops.
- Resolve chained member bases through the existing offset-commented source
  field context instead of a Sort- or Diagram-specific field table.
- Materialize bounded retained C probes for source occurrences such as
  `data->popup_gobj->hsd_obj`, preserving `source_hunks`, retained source
  provenance, pcode metadata, and `target_score`.
- Preserve terminal proof behavior when all bounded chained candidates miss.

## #1144 Proof

The reporter workflow now generates two retained field-load source probes for
`fn_802461BC` from the original pcode lead:

- `window-order-field-load-ig42-after-same-offset-chained-source-field-0`
- `window-order-field-load-ig42-after-same-offset-chained-source-field-1`

Both probes include retained source, retained pcdumps, source hunks, and
force-phys target scores. The best candidate moved IG42 from r29 to r28
against requested r27, but did not hit the target. The terminal handoff is to
recombine the best retained field-load probe with the retained
`temp-introduction-0` and `adjacent-decl-swap-0` candidates.
