# Indexed byte helper-result steering

## Goal

Make `debug select-order-search` produce source probes for a GPR byte-result
temporary when the byte load is hidden behind a source-visible `u8` helper, and
make window-order fallback diagnostics rank source-visible indexed-byte owners
for the reported byte-mask `rlwinm rX,rY,0,24,31` pcode shape. The reported
shape assigns a helper result to an integer local and applies the compiler's
byte-width mask; its pcode has an `lbz`/`rlwinm` result but no unique
caller-side byte-array expression.

## Decision

Add a narrow `indexed_byte_address_temp_steering` materializer for a verified
`u8` helper result. It introduces one fresh block-scoped `u8` local, then
splits the existing assignment into the helper call and an integer assignment:

```c
byte_result = Helper(...);
name_id = byte_result;
```

The existing transform-corpus orchestration will retain, score, and validate
the resulting candidates with its normal real-tree and force-phys pipeline.

Also allow the existing window-order implicit-temp owner path to continue past
only the exact `rlwinm ...,0,24,31` byte-mask wrapper, so it can populate and
materialize ranked indexed-byte source candidates instead of stopping at
`synthetic-temp-unsupported-shape`.

## Constraints

- Match only a source-visible helper with return type `u8`.
- Rewrite exactly one simple helper-call assignment in the selected function.
- Reject calls with side effects or ambiguous/multiple occurrences.
- Keep the original assignment's destination and surrounding control flow.
- Never manufacture a generic source temp from assembly alone; the `rlwinm`
  fallback only unlocks existing ranked C-source indexed-byte candidates.

## Verification

Tests will cover the reported multiline masked call assignment, successful
family materialization through `select-order-search --no-compile-probes`, and
rejections for non-byte helpers, side-effecting arguments, and ambiguous call
sites. Tests will also cover `rlwinm r79,r59,0,24,31` materializing ranked
indexed-byte source candidates. Focused transform-corpus, window-order, and
select-order suites will run before merge.
