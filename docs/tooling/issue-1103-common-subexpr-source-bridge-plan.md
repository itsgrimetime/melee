# Issue #1103 Common-Subexpr Source Bridge Plan

## Root Cause

The retained GPR common-subexpression coalesce source family stopped at
`common-subexpr-bridge-unavailable` when `debug suggest coalesce --discover`
reported a pcode-only pair. In the Sort retained frontier, the useful pair is
`r35/r42 -> r39`: the IR proves both candidate values come from the same source
virtual, but none of the pair facts carry a source bridge. Because the family
required pair-side source variables before it considered source-owner rewrites,
it never reached the existing shared-base or reuse-owner materializers.

## Implementation

Keep the direct bridge path unchanged for pairs whose facts already map to
source variables. For pcode-only pairs with valid shared-source IR proof, scan
only the target function for a conservative source-owner shape:

- at least two writes with the same normalized RHS;
- the RHS is a bare identifier;
- the written variables are pointer typed;
- at least two candidate writes have the same pointer type.

When that bounded shape exists, reuse the existing common-source shared-base and
reuse-owner materializers. The generated payload records
`source_owner_origin=implicit-repeated-pointer-rhs` and
`source_owner_resolution=pcode-shared-source-repeated-rhs` so downstream
diagnostics can distinguish this fallback from direct source bridges.

## Diagnostics

No-bridge pairs now report stronger terminal blockers when no safe source owner
can be found:

- `common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs`
- `common-subexpr-repeated-rhs-type-mismatch`

This keeps the old generic bridge-unavailable blocker from hiding whether the
IR proof failed or the source owner was simply unavailable.

## Verification

Regression coverage includes direct transform-family tests for:

- the pcode-only no-bridge `r35/r42 -> r39` path;
- missing repeated pointer RHS;
- repeated RHS with incompatible pointer-owner typing.

Command-level smoke coverage verifies `debug search plan-transforms
--coalesce-suggest-json` writes the implicit source-owner probe.
