# Force-Phys Temp Probes And Simplify Cap Design

## Context

Issues #751 and #752 are follow-ons to the force-phys select-order work. The current select-order beam composes transform-corpus probes, but the concrete transform families stop short of two source-visible levers reported by matching agents:

- FPR product temporaries in `mnDiagram_DrawCellNumber`, where row/column product expressions are source-bound but unsafe for generic statement motion.
- Indexed byte-array reads in `mnDiagram_SortNamesByKOs`, where the residual is an implicit base+index address temporary rather than a named byte value.

Issue #753 is a bounded-search bug in `debug mutate simplify-order`: after compiling the requested number of candidates, the search can enter the next source adapter before checking the cap, so an expensive adapter can make the command look hung before final reporting.

## Design

The source-probe additions stay inside the existing transform-corpus families. `coloring_register_steering` will add FPR product-temp anchors that split a source product into a temporary and, when two product assignments are present in one block, a paired split variant that perturbs both product lifetimes together. The anchors remain conservative: top-level function-body statements only, unique exact spans, proven FPR/scalar operands, no preprocessor regions, no synthetic split locals, and replacement through the existing span-validated mutator path.

`indexed_byte_address_temp_steering` will add index-temp anchors. These introduce an `int` index local, assign the original index expression to it, and keep the source read as `base[index_temp]`. This preserves the byte-array indexed access shape while perturbing index lifetime. The generator will reject side-effecting or ambiguous index expressions and use fresh names derived from the array leaf.

`simplify_search.search()` will enforce `max_candidates` before source-adapter entry and before pulling the next variant from an active adapter. Once the compile cap is reached, the driver returns the accumulated `SearchResult` without asking later adapters or the current adapter to yield another candidate. This fixes the reported post-compile stall without changing scoring, rendering, or candidate ordering before the cap.

## Verification

Regression tests will cover:

- A capped simplify-order search does not call later source adapters or pull a post-cap candidate from the active adapter after reaching `max_candidates`.
- FPR product-temp split and paired product-temp split probes are materialized for DrawCellNumber-style source and carry traceable payload metadata.
- Indexed byte index-temp probes are materialized for SortNames-style source, keep the indexed byte read form, and appear inside the reported command's eight-probe budget for condition-expression reads.
- Family registry metadata and mutator dispatch include the new concrete probe keys.

Focused CLI smokes will run the reported `debug select-order-search` commands with `--no-compile-probes --json` to confirm the probe lists contain the new families. The simplify-order smoke will run a small bounded command and confirm it returns a final report.
