# Frame And Inline Attribution Spec

## Goal

Resolve tooling issues #800 and #801 by improving diagnostic attribution for two residual classes:

- Select-order inline-boundary lanes must expose the concrete checkdiff opcode/call hunk that caused structural guard rejection, plus source-transform routes beyond call-argument tempization.
- Frame-reservation reports must identify source local arrays that explain same-frame address-taken local-area ranges currently reported as anonymous outgoing floor, and frame-transform scoring must rank probes against that local-area objective even when frame sizes already match.

## Constraints

- Keep changes scoped to `tools/melee-agent` diagnostics and tests.
- Preserve existing command behavior and JSON fields; add fields without removing established ones.
- Do not rerun checkdiff after temporary source restoration for #800. Use the `_SourceCandidateRealScore.checkdiff_payload` captured while the candidate source is installed.
- Keep raw checkdiff payload private. It may be stored on an internal variant key long enough to build summaries, but must be stripped from final JSON.
- Source attribution for #801 must be conservative. Attribute only literal local arrays with a byte size equal to the expected anonymous address-taken range and with evidence of address materialization such as array decay or `&name`.
- When attribution succeeds, emit source-actionable transform routes using existing CLI flags: `debug mutate frame-transform-search --include-transform-corpus --transform-family ...`.

## Design

### #800 Select-Order Inline Boundary

The select-order real-tree scorer returns `_SourceCandidateRealScore`; the select-order candidate path must retain its `checkdiff_payload` alongside `structural_guard` under a private `_checkdiff_payload` key. Guard-repair summaries convert that payload into compact `checkdiff_drift` evidence:

- `classification.inline_boundary_artifact` when present.
- The first raw unified diff hunk.
- A derived opcode/call hunk from `target_asm` and `current_asm`, including raw snippets and normalized opcode/call signatures.
- Repair routes for structure-axis scoring, select-order guard repair, transform-corpus plan inspection, and select-order transform-corpus repair preserving known force-phys and target-order goals.

Before emitting final select-order JSON, remove `_checkdiff_payload` and other private keys from ranked variants.

### #801 Frame Source-Array Attribution

Add optional source context to `analyze_frame_reservations`. The analyzer parses the target function body, identifies literal local arrays with known byte sizes, and detects address materialization evidence. If `frame_first_divergence.expected` is an anonymous address-taken range whose size matches such a local array, and the expected range starts immediately after the expected low floor while the current low floor covers that range, replace the unresolved attribution with `identity_kind=source-local-array-size-range`.

The new cause kind is `local-area-vs-outgoing-floor-divergence`. It updates the verdict to `source-reachable-candidate`, adds transform-corpus route hints, and activates a local-area frame-transform objective. That objective scores candidates by remaining bytes of the attributed expected range still covered by the candidate low unused floor, with transform force-phys metadata as a ranking bonus when present.

## Acceptance

- Tests prove #800 lane summaries include `checkdiff_drift.opcode_hunk`, the raw diff hunk, expanded transform routes, and no raw private checkdiff payload in final variants.
- Tests prove #801 attributes a 480-byte expected address-taken range to `totals[0x78]` and changes the cause kind to local-area/outgoing-floor divergence.
- Tests prove frame-transform evaluation ranks a local-area-fixing candidate ahead of a neutral same-frame candidate and reports `source-reachable-local-area-transform`.
- Narrow test suite passes.
- CLI smoke checks for `debug select-order-search --help`, `debug inspect frame-reservations --help`, and `debug suggest frame --help` pass.
