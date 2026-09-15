# Harvest negative-evidence rebucket plan

Issues: #477 and #478.

## Problem

Harvest can answer a bounded current-tool question without producing a match.
Those rows currently remain in executable source-actionability lanes, causing
later campaigns to rerun the same exhausted probe.

## Design

Reuse the prior-ledger `source_actionability_rebucket` overlay introduced for
data-symbol rows.

### Register allocator

Trigger on `register-allocator` rows with
`source_actionability=pcdump-proof-needed` when allocator pcdump triage returns
`status=no_match` and blocker `allocator-force-vector-no-match`.

Map the target-vector evidence to:

- `source-lifetime-callee-save-shape` when
  `target_vector_actionability.status=already-satisfied`.
- `allocator-target-conflict` when the payload reports force-vector conflicts or
  a non-runnable/non-recommended force vector.
- `allocator-target-vector` for other needs-move force-vector no-match evidence.

Each rebucket keeps allocator details, force-vector verification evidence, and
a source/taxonomy fingerprint plus row-tool and tool-code signatures so evidence
expires when the source, taxonomy row, harness command fields, or relevant debug
tool code changes.

Rows rebucketed out of `pcdump-proof-needed` must not auto-select allocator
pcdump triage solely because the stale taxonomy row still has `mwcc-debug` or
`debug dump local` metadata. Explicit target-map harness overrides remain
available for manual reruns.

### Stack current-tools

Trigger on `stack-local-layout` frame-transform rows with
`source_actionability=current-tools` and
`frame_closability_tier=current-tools-padstack` when the harness returns
`status=no_match` and blocker `no-validated-candidate` with scored candidates.

Map to:

- `diagnostic-only` when the best candidate label/operator indicates
  PAD_STACK/frame-reservation diagnostic evidence.
- `source-probe` for other scored frame-transform candidates.

Each rebucket keeps candidate detail and a source/taxonomy fingerprint plus
row-tool and tool-code signatures so evidence expires when the source, taxonomy
row, harness command fields, or relevant debug tool code changes.

Rows rebucketed out of `current-tools` must not auto-select frame-transform
solely because stale `headline_tool=frame-transform-search` or
`frame_closability_tier=current-tools-padstack` metadata remains in the queue.

## Tests

- Register allocator force-vector no-match rebuckets already-satisfied evidence
  to `source-lifetime-callee-save-shape`.
- Register allocator force-vector no-match with conflicts rebuckets to
  `allocator-target-conflict`.
- Register allocator force-vector no-match with needs-move evidence rebuckets to
  `allocator-target-vector`, and non-runnable force vectors rebucket to
  `allocator-target-conflict`.
- Register allocator force-vector no-match rows outside `pcdump-proof-needed`
  do not rebucket.
- Fingerprinted register allocator ledgers remove answered rows from
  `pcdump-proof-needed` previews and stop selecting allocator pcdump triage for
  the rebucketed row.
- Frame-transform no-validated current-tools rows rebucket to `diagnostic-only`
  for PAD_STACK evidence and to `source-probe` for other scored candidates.
- Fingerprinted frame-transform ledgers remove answered rows from
  `current-tools` previews and stop selecting frame-transform for the rebucketed
  row.
- Guard tests keep rows executable when no scored candidate exists or source
  actionability does not match the current-tools lane.
