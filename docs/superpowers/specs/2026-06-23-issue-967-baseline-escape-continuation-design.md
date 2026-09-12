# Issue 967: Baseline-Escape First-Divergence Continuation Design

## Problem

`debug search baseline-escape` now generates and scores post-ceiling source baselines for Draw and Sort, but it stops at a first-generation no-progress terminal. The matcher then manually ran `debug inspect first-divergence` on retained candidate pcdumps and found actionable allocator cases. That evidence is text-only today because allocator-mode `first-divergence --json` errors unless `--frame` is used.

The missing layer is a scored-candidate continuation pass: after baseline-escape candidates score with retained pcdumps and no target/expression progress, the tool should inspect each retained pcdump, classify the first divergence, and emit either concrete second-generation routes or a structured terminal blocker.

## Approach

Use the existing first-divergence analyzer as the source of truth.

1. Add allocator-mode JSON serialization to `debug inspect first-divergence`.
2. Extend `post_ceiling_baseline_escape.py` to analyze scored candidate `pcdump_path` values when all generated candidates were scored with no progress.
3. Emit a `post_ceiling_continuation` summary before declaring the first-generation terminal:
   - `status=actionable` when at least one candidate has a concrete continuation route.
   - `status=terminal` with `kind=post-ceiling-continuation-exhausted` when every retained pcdump is unsupported or unavailable.
4. Teach retained-frontier triage that `post-ceiling-continuation-exhausted` is a distinct terminal suppression family from the first-generation baseline-escape terminal.

## Route Rules

- Case C / C2: emit a retained `debug select-order-search` route using the candidate pcdump, force map, class id, and a target order anchored on the divergent IG. This is source-actionable because select-order-search can generate and score probes from retained source/pcdump evidence.
- Case D: emit a retained coalesce/split route. If source attribution is class-inconsistent or missing, mark it as `unsupported-source-attribution` instead of pretending a GPR symbol is an FPR anchor.
- Pcode-only FPR stack-load/conversion first-defs such as `lfd f46,@1539(r1)`: emit `unsupported-source-attribution` with the first-def text and no route.
- Pcode-only GPR implicit add/addi temps: emit a select-order route only when it is not one of the suppressed indexed-byte/source-owner families; otherwise mark the suppressed-family blocker explicitly.

## Output Shape

Baseline-escape classified output gains:

- `post_ceiling_continuation.status`
- `post_ceiling_continuation.routes[]`
- `post_ceiling_continuation.blockers[]`
- `post_ceiling_continuation.terminal_summary` when exhausted

Each route includes `candidate_id`, `case`, `class_id`, `ig_idx`, `baseline_reg`, `target_reg`, `pcdump_path`, `source_retained` when known, and a runnable command hint.

## Tests

- First-divergence allocator JSON includes gated fact and advisory source fields.
- Baseline-escape with no-progress scored candidates and retained pcdumps emits a Case C/C2 select-order continuation route instead of only the first-generation terminal.
- Unsupported FPR stack-load/conversion first-defs emit a continuation-exhausted blocker.
- Retained-frontier triage extracts `post-ceiling-continuation-exhausted` as its own terminal family.

## Scope Boundaries

This feature emits second-generation routes and terminals. It does not run the potentially expensive continuation searches automatically in baseline-escape. Matchers can run the emitted commands in their worktree, retain probes, and feed the resulting JSON back into the existing retained-frontier/allocator flow.
