# select-order-search residuals and source restore guard

## Problem

`debug select-order-search` ranks source-shape candidates by select-order objective, but when the top candidates still miss a force-phys proof target the command does not summarize why each candidate remains blocked. Matching agents must manually replay first-divergence for each candidate pcdump/source and can lose the candidate-specific context.

The same command can also leave generated probe edits in the live source file during compile-only runs. The real-tree match-percent helper has its own restore path, but `select-order-search` does not guard the whole source-candidate compile/scoring path, so a lower-level compile helper leak contaminates later beam/focused runs.

## Requirements

- Add `--force-phys IG:PHYS[,IG:PHYS]` as a `select-order-search` alias for the existing proof-force map used by directed transform probes.
- When a force-phys map is supplied and ranked candidates miss the target, attach residual first-divergence summaries to the top ranked successful candidates.
- Add `--residual-first-divergence-top N`, defaulting to automatic top-3 residuals when `--force-phys` or `--transform-force-phys` is present and no ranked candidate satisfies the full force-phys map.
- Residual summaries must include the candidate label/source, class, normalized force-phys map, allocator case, ig binding, baseline/target physicals, blocker/coalesce facts, local target, opcode/frame status, and candidate objective.
- Candidate sources from generated/campaign directories must be reported as the retained candidate path, not by mutating or reading stale live source.
- Every source-candidate compile/scoring attempt must restore the live source bytes exactly, including `--no-score-match-percent` runs.
- If live-source restoration fails, the command must preserve the original live-source bytes at a backup path and surface that path in the failed variant/error.

## Design

`select-order-search` will retain each successful candidate's compiled pcdump text in an in-memory map keyed by variant object identity, avoiding duplicate-label ambiguity. The map is not serialized directly. After ranking, the command decides whether residual analysis is active:

- explicit `--residual-first-divergence-top 0` disables it;
- explicit positive values enable it for that many top successful candidates;
- omitted value enables top-3 only when a proof force map is supplied and no successful variant's pcdump already satisfies the full force-phys target.

Residual analysis parses the candidate pcdump with the existing `mwcc_debug.first_divergence` analyzer, then serializes a command-owned residual payload. The payload includes candidate label/source, status, class, normalized force-phys map, gated allocator fact fields, advisory source idea fields when available, objective snapshot, opcode-shape status, frame delta, and a candidate-specific `next_source_lever`. Source ideas are advisory and best-effort: if a retained candidate source exists, the analyzer tries to attach source bindings using the candidate source and candidate pre-coloring pass. If mapping fails, the residual still emits gated allocator facts and marks source ideas as unavailable.

The source-restore fix wraps the complete `.c` candidate scoring path in byte-based source snapshot machinery. For each source candidate, `select-order-search` snapshots the live target source resolved from the function using `read_bytes`, registers a text-compatible signal snapshot when the file decodes cleanly, executes `compile_source_variant` and optional real-tree match-percent scoring, then restores and verifies exact bytes in a `finally` block. A restore failure writes the original bytes to a backup file under `build/source-restore-backups/`, raises, and the failed variant records the restore diagnostic, backup path, and retained probe source path.

## Non-goals

- Do not make allocator residuals infer force-phys targets from virtual order alone.
- Do not persist compiled pcdumps to new files.
- Do not change lower-level `compile_source_variant` behavior beyond guarding it at the command boundary.
