# Issue #959 Node-Set Pending Resume Design

## Context

Issue #959 reports that `mwcc-debug` node-set splitting can spend the full
`--budget` generating source candidates, then exit before any scoring or
retention artifact exists.

Live issue facts:

- Function: `mnDiagram_DrawCellNumber`.
- Tool: `mwcc-debug`.
- Existing command: `melee-agent debug solve node-set-split`.
- Coupled FPR run used `--max-candidates 8 --budget 90 --timeout 30
  --retain-generated --json` and returned `status=exhausted`,
  `stop_reason=budget-exhausted`, `generated_count=0`, `scored_count=0`,
  and no pending metadata.
- Single-IG checks generated many pending candidates, scored none, retained no
  generated candidate list/source metadata, and only recommended rerunning with
  a larger `--budget`.

The capability audit confirmed the existing command:

```bash
melee-agent capabilities search "node-set-split pending resume budget-aware generation scoring candidates"
```

Result: `debug solve node-set-split`. The fix should extend that command; it
should not add a brand-new top-level tool.

Current implementation observations from `/Users/mike/code/melee`:

- `tools/melee-agent/src/cli/debug/__init__.py` is already dirty from unrelated
  local work. Any implementation must inspect and preserve those hunks.
- `solve_node_set_split_cmd` computes `candidate_limit` from `--max-candidates`,
  but the single-IG generator calls do not pass that limit into
  `generate_node_set_split_patches` or
  `generate_node_set_introduce_binding_patches`.
- Coupled generation passes a limit, but its deadline checks can return no
  partial candidate metadata when generation expires.
- `_node_set_split_resume_manifest_path(summary_path)` exists, and
  `_node_set_split_load_resume_summary` detects whether the manifest exists,
  but no code currently writes or consumes a node-set resume manifest.
- Final summaries only attach a resume command for `candidate-limit`, not for
  `budget-exhausted`, even when unscored generated candidates exist.

## Goals

- Preserve generated node-set candidates whenever budget exhaustion prevents
  scoring.
- Let `--resume-summary` continue from retained generated candidates without
  regenerating them.
- Make `--max-candidates` bound generation for single-IG paths as well as the
  later scoring loop.
- Keep the solution under `debug solve node-set-split`.
- Keep summaries actionable: a budget-exhausted run with pending candidates
  must include retained candidate metadata and a copyable resume command.

## Non-Goals

- Do not add a new top-level command.
- Do not change decompiled production C source.
- Do not require raw HTTP/curl or decomp.me API access.
- Do not make node-set matching decisions for `mnDiagram_DrawCellNumber`; this
  is a tooling reliability fix.

## Approaches Considered

### Approach 1: Generation Cap And Budget Reserve Only

Pass `candidate_limit` into every generator and stop generation early enough to
leave budget for baseline/candidate scoring.

Pros:

- Smallest code change.
- Directly addresses single-IG runs that generated 24/27 pending candidates
  before scoring.

Cons:

- If generation still consumes the budget, the generated source list is lost.
- Coupled generation can still return no useful handoff if no complete coupled
  patch is produced before the deadline.
- Does not use the existing resume-manifest hook.

### Approach 2: Manifest-First Pending Candidate Retention

After candidate generation and ordering, write a resumable manifest before
baseline compilation or candidate scoring. Store candidate source files plus
stable metadata next to the JSON summary, then teach `--resume-summary` to load
that manifest and score retained candidates.

Pros:

- Solves the core data-loss failure: generated candidates survive even if
  budget expires before scoring.
- Reuses the existing `_node_set_split_resume_manifest_path` concept.
- Works for budget exhaustion before baseline compile, before candidate compile,
  or before checkdiff scoring.
- Makes a resumed run deterministic because candidate IDs and source files are
  fixed.

Cons:

- Slightly larger implementation.
- Requires manifest validation and careful output-path handling.

### Approach 3: Streaming Generator/Scorer

Refactor node-set generation into iterators and score each candidate as soon as
it is yielded.

Pros:

- Best long-term time-to-first-score behavior.
- Avoids materializing a large candidate list in memory.

Cons:

- Most invasive.
- Harder to layer onto coupled generation, steering children, and existing
  summary accounting.
- More likely to disturb unrelated solver behavior.

## Selected Design

Use Approach 2, plus the bounded-generation fix from Approach 1.

The implementation should remain a scoped extension to
`melee-agent debug solve node-set-split`:

1. Pass the existing `candidate_limit` into single-IG generation.
2. Retain an ordered candidate manifest as soon as candidates exist.
3. Include a resume command for budget-exhausted runs with pending candidates.
4. On `--resume-summary`, load the manifest when present and score retained
   sources without regenerating candidates.

This is the smallest change that prevents issue #959's failure mode while
making the existing resume surface real.

## Manifest Schema

Write the manifest to:

```text
<summary>.manifest.json
```

Write generated source files to a sibling directory:

```text
<summary-stem>.candidates/
```

Manifest version 1:

```json
{
  "version": 1,
  "kind": "node-set-split-generated-candidates",
  "function": "mnDiagram_DrawCellNumber",
  "class_id": 1,
  "source_file": "src/melee/mn/mndiagram.c",
  "source_sha256": "...",
  "request": {},
  "coupled_requests": [],
  "candidate_order": ["node-split-..."],
  "candidates": [
    {
      "index": 0,
      "candidate_id": "node-split-...",
      "summary": "Introduce alias...",
      "touched_ranges": [[120, 180]],
      "source_path": "build/diagnostics/.../node_set_split.candidates/node-split.c",
      "source_sha256": "...",
      "hunk": "@@ ...",
      "metadata": {}
    }
  ]
}
```

Summary additions:

```json
{
  "manifest_path": "build/diagnostics/.../ig32_col_offset_f28.manifest.json",
  "generated_candidate_manifest": "build/diagnostics/.../ig32_col_offset_f28.manifest.json",
  "pending_candidates": [
    {
      "candidate_id": "node-split-...",
      "source_path": "build/diagnostics/.../node-split.c",
      "summary": "Introduce alias..."
    }
  ],
  "resume_mode": "manifest"
}
```

`pending_candidates` should be a compact summary list, not full source text.
The manifest owns source retention.

## Resume Behavior

When `--resume-summary PATH` is supplied:

- If `PATH.with_suffix(".manifest.json")` exists, load it and set
  `resume_mode="manifest"`.
- Reconstruct `CandidatePatch` objects from manifest source files, preserving
  candidate ID, summary, hunk, touched range, and metadata.
- Do not call source-generation functions on the manifest path.
- Validate function and class compatibility.
- Validate the original source hash and retained candidate source hashes; fail
  with exit 2 if the source file or a retained candidate is missing or modified.
- Score pending candidates from the manifest. Already-scored rows from the
  prior summary may be preserved in the merged output, but they must not block
  pending candidates from being scored.
- Treat candidates with `score.status == "budget-exhausted"` or
  `objective.status == "realized"` but no `checkdiff_pct/checkdiff_delta` as
  still pending for resume purposes; they compiled far enough to need
  checkdiff scoring, not final classification.
- Keep the existing `regenerated-no-manifest` fallback for older summaries.

## Stop Conditions And Resume Commands

Budget-exhausted summaries should include a resume command when any generated
candidate is unscored:

```text
melee-agent debug solve node-set-split ... --resume-summary <summary> --output <summary> --max-candidates 0 --json
```

This should apply to:

- budget exhausted before baseline compile,
- budget exhausted before the first candidate compile,
- budget exhausted after objective evaluation but before checkdiff scoring,
- candidate-limit stops with omitted candidates.

The summary should keep `status="exhausted"` and `exhaustive=false` for these
bounded or budgeted runs. It must not imply the source-shape family is
terminally exhausted while pending manifest candidates remain.

## Candidate Limits

`--max-candidates N` should cap the ordered generated candidate list for
single-IG runs before baseline/scoring work begins. `--max-candidates 0` keeps
the current unlimited behavior.

Implementation detail:

- `generate_node_set_split_patches(..., max_candidates=candidate_limit, ...)`
- `generate_node_set_introduce_binding_patches(..., max_candidates=candidate_limit, ...)`
- Coupled generation should continue to receive `max_candidates` and should not
  discard any complete candidates already built when the deadline expires.

If a candidate cap truncates generation, the summary should expose
`stop_reason="candidate-limit"` only when scoring stops because of the cap or
the manifest contains omitted generated candidates. If generation itself is
bounded to the cap, include a clear generation truncation flag such as:

```json
{
  "generation_truncated": true,
  "candidate_limit": 8
}
```

## Regression Coverage

Add or update focused tests in
`tools/melee-agent/tests/search/solver/test_cli_solve.py`.

Required tests:

- Single-IG generation honors `--max-candidates` before scoring:
  monkeypatch the generator, assert it receives `max_candidates=2`, and assert
  only two generated candidate IDs are retained.
- Budget exhaustion before baseline compile writes a summary and manifest:
  run with `--budget 0 --retain-generated --output <tmp>/summary.json --json`;
  assert `manifest_path` exists, retained source files exist, `pending_count`
  equals generated count, `scored_count == 0`, and `stop_condition.resume_command`
  includes `--resume-summary <summary>`.
- Resume with manifest scores retained pending candidates without regeneration:
  create or reuse a summary/manifest, monkeypatch all generation functions to
  fail if called, invoke `--resume-summary <summary>`, and assert candidate IDs
  from the manifest are compiled/scored.
- Coupled resume with manifest scores retained pending candidates without
  regeneration and preserves `coupled_requests`.
- Existing resume fallback remains intact:
  keep or update the current `regenerated-no-manifest` test so old summaries
  without manifests still regenerate.
- Budget exhaustion after objective realization but before checkdiff scoring
  still retains candidate source and emits a manifest-backed resume command.
- Budget exhaustion with `--retain-generated --json` and no explicit `--output`
  writes the default summary path, writes the manifest, and points the resume
  command at that default summary.

Command-level smoke checks after implementation:

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py \
  -k "node_set_split and (budget or resume or max_candidates)"

python -m pytest tools/melee-agent/tests/search/solver/test_solve.py

python -m py_compile \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/mwcc_debug/node_set_split.py

melee-agent debug solve node-set-split --help | \
  rg -- "--resume-summary|--retain-generated|--max-candidates"
```

Optional live smoke, if the referenced diagnostics exist:

```bash
/opt/homebrew/bin/melee-agent debug solve node-set-split \
  -f mnDiagram_DrawCellNumber \
  --class fpr \
  --node-set-delta build/diagnostics/mndiagram_958_rerun/draw_solve_coloring_live.json \
  --source-file src/melee/mn/mndiagram.c \
  --force-phys '32:28,37:26,46:26' \
  --coupled \
  --max-candidates 2 \
  --budget 1 \
  --timeout 1 \
  --retain-generated \
  --output build/diagnostics/issue_959_smoke/node_set_split.json \
  --json
```

Then inspect:

```bash
jq '.manifest_path, .pending_count, .stop_condition.resume_command' \
  build/diagnostics/issue_959_smoke/node_set_split.json
```

## Guardrails

- Do not overwrite unrelated dirty hunks in
  `tools/melee-agent/src/cli/debug/__init__.py`; inspect `git diff` before and
  after editing.
- Do not touch decompiled source under `src/melee/`.
- Do not add a new top-level command.
- Do not resolve issue #959 or commit as part of implementation unless the user
  explicitly asks.
- Keep manifest source files under `build/diagnostics` or
  `build/mwcc_debug_cache`; do not write retained generated sources into the
  source tree.
- Validate manifest candidate hashes on resume before compiling.
- Make manifest writes atomic enough for interrupted runs: write candidate
  files first, then write the manifest JSON last.
- Keep the first implementation focused on complete `CandidatePatch` objects
  returned to the CLI. Do not refactor coupled generation internals unless a
  focused test proves complete candidates are being discarded inside the
  generator.

## Success Criteria

- A budget-exhausted node-set run with generated candidates emits retained
  candidate metadata and a resumable manifest.
- The resume command scores manifest candidates without regenerating them.
- `--max-candidates` prevents single-IG generation from expanding far past the
  intended bounded candidate set.
- Existing solver and node-set-split CLI behavior remains compatible for older
  summaries without manifests.
