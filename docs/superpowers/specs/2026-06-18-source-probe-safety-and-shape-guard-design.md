# Source Probe Safety And Shape Guard Design

## Context

Issues #786, #787, and #788 are one batch of tooling failures in allocator-directed source probing:

- #786: node-set-split decl-order candidates can duplicate existing local declarations, then fail later as compiler/pcdump failures.
- #787: `debug search plan-transforms --node-set-delta --write-probes` can still enumerate expensive unrelated source families and hang instead of returning a bounded node-set plan.
- #788: target-vector/select-order source scoring can rank a register-allocation win above a candidate that preserves function shape, even when checkdiff classifies the candidate as structural drift.

The user delegated decisions and asked for no human review gate, so this spec uses the existing issue bodies as approval input and relies on independent Codex review before implementation.

## Design

The fix keeps each behavior at the existing boundary that already owns it.

For #786, node-set-split decl-order generation must handle tree-sitter byte ranges correctly when Python slices source strings. The observed duplicate-local candidates were caused by UTF-8 byte offsets being used as character indexes after non-ASCII text before the target function. The primary fix converts tree-sitter byte ranges before slicing declaration lines and initializer text. A secondary safety lane still rejects any generated decl-order patch that would introduce duplicate local declarations in one scope; rejected candidates are carried as metadata-bearing source-rejected patches so CLI accounting can explain them without compiling malformed source.

For #787, transform-corpus planning treats an explicit `--node-set-delta` as a bounded, targeted materialization request unless the caller explicitly asks for more families. Node-set split and introduce-binding generators accept a real candidate budget and stop source generation once that budget is filled. Coupled multi-IG planning is deferred until single-target probes fail to fill the budget. After node-set-delta register-steering probes are materialized, the orchestrator returns immediately for default-family calls. The CLI reports a planning `stop_condition` so write-probe runs have terminal evidence even when targets are capped, omitted, or blocked.

For #788, real-tree source scoring optionally runs a no-build checkdiff structural guard after a successful candidate build, while the candidate source is still applied under the source-scoring lock and before the restore guard runs. The guard records checkdiff primary classification, normalized structural diff count, opcode similarity, line/hunk counts, frame sizes, frame delta, and a boolean `shape_preserved`. A candidate is shape-preserving only when checkdiff reports an effective structural classification (`instruction-identical`, `relocation-label-only`, `normalized-structural-match`, or zero-normalized register/operand/backend evidence) and any known frame delta is compatible. `debug target score-source --json --checkdiff-guard` exposes this metadata. Select-order search requests the guard for force-phys source candidates, attaches the metadata to variants and beam ledger entries, and demotes candidates whose target-vector score improves by changing opcode/normalized shape.

## Success Criteria

- #786 regression: generated node-set-split decl-order candidates do not duplicate existing locals; CLI JSON can report `source-rejected` rows with a rejection reason.
- #787 regression: node-set-delta transform planning with default families returns only node-set-delta probes without iterating unrelated source anchor generators.
- #788 regression: select-order ranking and beam ledger include structural guard metadata, and structurally drifting candidates are ranked below comparable shape-preserving candidates even if they improve requested registers.
- Existing tests around node-set-split, transform-corpus, `debug target score-source`, and select-order continue to pass.
