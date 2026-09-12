# Issue 1117: mnDiagram3 Frame Outgoing-Floor Source Probes

## Problem

`mnDiagram3_80245BA4` had a same-frame outgoing-parameter floor mismatch:
the current frame reserves more low outgoing-parameter words than expected,
but the frame-transform workflow only emitted generic block/lifetime probes.
Those probes were not enough to tell the matcher whether a bounded source
family had been exhausted.

## Plan

- Treat an attributed outgoing-parameter floor delta with no accesses in the
  excess floor as a request for retained `outgoing_parameter_area_shape` probes.
- Keep generated source hunks, retained source paths, retained pcdumps, and
  frame/checkdiff scoring data on compiled frame-transform variants.
- Broaden the safe FP lifetime probe generator from literal-only locals to
  simple globals and expression values when the source shape is side-effect
  free.
- Add terminal proof for the outgoing-parameter family so zero-improvement or
  worse-than-baseline retained probes produce a concrete source-level handoff.

## Verification

- Unit coverage checks that `frame-transform-search` auto-enables the outgoing
  family and retains source hunks in JSON.
- Unit coverage checks terminal proof includes retained source, pcdump, hunks,
  and checkdiff metadata for bounded outgoing-parameter probes.
- Reporter smoke for `mnDiagram3_80245BA4` generated twelve retained probes,
  including nine `outgoing_parameter_area_shape` probes, all measured with
  retained pcdumps and source hunks. No candidate improved the two-word
  parameter-area surplus, so the terminal proof now reports the bounded family
  exhausted and hands off to source-level lifetime/order modeling.
