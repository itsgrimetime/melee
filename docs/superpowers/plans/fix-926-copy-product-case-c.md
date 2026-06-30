# Issue 926: GPR Copy-Product Case-C Repair Plan

## Root Cause

`mnDiagram_SortNamesByKOs` exhausted the existing
`pcode_only_gpr_address_temp_repair` lane. That family only rewrites indexed
`sorted_names[...]` loads and base-copy/address-temp spans. The latest retained
frontier needs a different source-actionable lever: a low-confidence pointer
local (`dst_iter`) and the pcode-only GPR copy-product owner around the
generated `ll_probe_iter_0` cursor/store.

The missing reusable class is a class-0 transform family that changes
source-visible pointer-owner/copy-product order without merely wrapping
indexed loads.

## Scoped Fix

Add `pcode_only_gpr_copy_product_case_c_repair` as a transform-corpus family.
The family should:

- detect byte-pointer owner loops with a matching `*owner = ...` store,
- relate them to the low-confidence `dst_iter` local when present,
- emit bounded exact-span source probes such as an output-owner copy before the
  loop or a store-owner temp,
- include payload diagnostics and source hunks for validation/reporting,
- avoid unrelated pointer products such as the `tp` totals loop.

Do not touch dirty shared CLI files or allocator-ceiling reporting in this
commit. Existing `plan-transforms` validation already preserves probe payloads
and validator `target_score` output.

## Tests

Add regression coverage for:

- registry metadata and mndiagram cluster routing,
- direct transform-corpus probe generation for the retained Sort pointer-owner
  shape,
- CLI JSON diagnostics from `debug search plan-transforms`.

Verify with focused pytest runs, syntax checks, and a retained-source
`plan-transforms` smoke against the reported artifact.
