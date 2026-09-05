# Issue 934: Copy-Product Source Owner Discovery

## Adopted narrow plan

Window-order source probing already handles GPR `implicit-temp` attributions by
parsing their virtual expression, finding the source owner, and materializing
either an owner split or ranked indexed-byte diagnostics. The narrowed fix keeps
that path as the single implementation point and only adds a bridge for
top-level GPR `copy/coalesce-product` attributions.

For a lead whose target attribution is `copy/coalesce-product`, the planner now:

1. Accepts only a GPR `mr rDST,rSRC` expression whose destination virtual equals
   the lead target IG.
2. Resolves the source virtual from `base_virtual` when present, otherwise from
   the parsed `rSRC` operand.
3. Looks up that source virtual in `source_attributions`.
4. Runs the existing source-kind planner behavior on the resolved attribution,
   including `_implicit_add_owner` for resolved `implicit-temp` sources.
5. Wraps the resulting synthetic metadata with the top-level copy-product
   context and full copy chain so diagnostics still explain how the original
   lead reached the owner.

Malformed expressions, destination mismatches, unsupported classes, and non-GPR
copy expressions keep the previous blocker behavior instead of broadening the
search surface.

## Reviewer adjustment

The original broader idea was to add a new source-owner discovery command.
Review narrowed the fix to the existing select-order path: load only the missing
copy-product source operands during source attribution, then let planner-level
owner discovery reuse the existing implicit-temp and indexed-byte
materialization code.

The real retained Case-C artifact confirmed both halves were needed. Without
expanding `copy/coalesce-product` operands, the attribution map stopped at IG34
and never loaded IG37. With IG37 available, the planner can follow
`mr r34,r37` into the existing `addi r37,r52,28` attribution.

## Regression coverage

Added focused tests in
`tools/melee-agent/tests/search/directed/test_window_order_source.py`:

- A top-level `copy/coalesce-product` lead for `mr r34,r44` resolves through
  virtual `44` to an `implicit-temp` add, then materializes the existing
  implicit-add owner split for the local operand.
- A valid GPR copy product whose source virtual has no attribution produces no
  probes and reports a clean `copy-product-source-unmapped` blocker with
  copy-product metadata.

Added focused coverage in `tools/melee-agent/tests/test_select_order_search.py`
for the source-attribution retry path so a top-level `copy/coalesce-product`
lead loads its source operand attribution on the second pass.
