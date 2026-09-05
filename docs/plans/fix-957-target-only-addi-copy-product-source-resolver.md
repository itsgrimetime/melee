# Fix 957: Target-Only Addi Copy-Product Source Resolver

## Context

Issue #957 covers target-only backprojection where the allocator lever is a
PCode-only `addi`, such as `addi r34,r52,28`. The prior allocator-ceiling
classifier treated retained simplify-probe exhaustion as enough to emit a
terminal `target-only-backprojection-source-probe-continuation` result with the
generic unsupported family `target-only-backprojection-addi-copy-product`.

That terminal was too broad. Simplify exhaustion only proves the retained probe
stream did not improve the force map. It does not prove the addi/copy-product
operands are non-source-visible, nor that source-visible address-owner variants
were tested.

## Scoped Design

Keep the fix inside allocator-ceiling classification and text rendering.

For target-only addi source levers:

- If matching retained simplify exhaustion is absent, keep the existing
  incomplete continuation that asks for retained source-probe exhaustion.
- If simplify exhaustion is present but resolver evidence is absent, keep the
  result actionable with an incomplete continuation. The continuation names the
  missing evidence kind:
  `target-only-backprojection-addi-copy-product-source-resolver`.
- If explicit resolver evidence is present and matches the active source lever,
  parsed addi PCode lever, and final force-phys map, classify the continuation
  as terminal and carry the resolver facts through the result.

The resolver evidence is intentionally small and JSON-shaped:

- `kind`: `target-only-backprojection-addi-copy-product-source-resolver`
- `status`: terminal status such as `terminal-non-source-visible`
- `complete`: `true`
- `source_lever`, `pcode_lever`, `final_force_phys`
- `attempted_targets`, `protected_targets`
- `copy_product_chain`
- `source_visible_variants`
- optional `source_file`, `pcdump`, `baseline_score`, `best_score`, and
  `terminal_blocker`

The classifier does not invent source visibility. It only upgrades to a
practical ceiling when this resolver summary is supplied and matches the active
backprojection context.

## Rendering

Text output should expose why the addi/copy-product path is terminal:

- the pcode lever,
- attempted and protected force targets,
- copy-product chain expressions,
- source-visible variant scores, and
- terminal blocker.

This replaces the generic unsupported-family explanation with source-actionable
missing evidence or concrete non-source-visible/copy-product facts.

## Verification

Regression coverage in `tools/melee-agent/tests/test_allocator_ceiling.py`
checks that simplify exhaustion alone remains actionable/incomplete, resolver
terminal evidence yields a practical ceiling with copy-product facts, and text
rendering includes the chain and source-visible variant scores.
