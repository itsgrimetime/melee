# Select-Order and Node-Set Diagnostics Design

## Context

Issues #776, #777, #778, #780, #781, and #782 all target the register-steering diagnostics used by matching agents on `mnDiagram_SortNamesByKOs` and `mnDiagram_DrawCellNumber`. The existing tools already expose the right entry points: `debug solve coloring`, `debug solve node-set-split`, and `debug select-order-search`. The failures are in attribution safety, candidate scoping, bounded generation, and diagnostic bucketing.

## Approaches Considered

Recommended: keep the existing commands and add focused guardrails/reporting. This preserves workflows and minimizes risk while fixing the reported blockers.

Alternative: create a new higher-level resolver command that wraps solve-coloring, node-set-split, and select-order-search. That would hide repeated commands, but it would duplicate ranking and source-restore behavior while these issues need safer primitives.

Alternative: add more source transform families first. The issue reports explicitly ask for better attribution and residual output before another transform wave, so this would continue producing hard-to-read misses.

## Design

Node-set delta assembly will treat low-confidence inverse source bindings as unsafe for direct split generation. If a virtual is attributed only by a low-confidence declaration-order binding, the emitted delta should still include the first-def/live-range evidence, but it must not claim a concrete source variable such as `dst_iter`. That turns #780 into an honest no-binding case instead of a misleading source action.

Node-set split requests will carry an optional source scope path derived from the delta source name and source line. Alias and lifetime probe generation will pass that scope to existing mutators, so repeated locals like `j` are only edited in the owning loop scope. If no scope can be resolved, generation falls back to current behavior. Compile failures for retained node-set candidates will expose the compiler/build error directly in JSON, so agents do not have to infer that a source probe failed from a secondary "function not found in pcdump" symptom. This addresses #781 without removing the broad fallback used by older deltas.

Coupled node-set generation will remain bounded. When a coupled request set is empty, or when two or more bindable requests produce zero patches, the CLI summary must explicitly report a zero-generated blocked state without compiling or scoring candidates. This addresses #782.

Select-order beam output will keep current ranking, but residual analysis will be attached by diagnostic buckets in addition to the global top N. Buckets will include exact-distance candidates, one-target force-phys hits, opcode/frame-preserving candidates, frame-preserving candidates, and per-force-entry hits. Buckets with no member should appear as empty arrays so absence is explicit. Each annotated variant should include its chain/probe provenance and compact source hunk/diff metadata already retained by the command. This addresses #778 and gives the #776/#777 partial-hit workflows readable next-source-lever data. The #776/#777 closure criterion is diagnostic: the command must identify the next source lever for relevant partial-hit buckets or explicitly show that no candidate exists in a bucket. It does not promise a new exact-match source transform.

## Testing

Regression tests will cover:

- Low-confidence source bindings are omitted from node-set deltas.
- Node-set split alias/lifetime probes stay inside the source scope for a repeated loop variable, and compile failures expose the retained source error directly.
- Coupled generation reports an immediate blocked/zero-probe summary for both empty coupled requests and bindable requests that produce zero patches.
- Select-order search annotates diagnostically relevant bucket candidates even when they fall outside the global top slice.
- Beam candidates expose transform/probe stack provenance in JSON.

Smoke checks will run the focused pytest suites for node-set split, solver CLI, and select-order search, followed by syntax checks and command-level CLI help/probe smoke tests.
