# Fix plan: issue #983 sort source-model synthesis

## Scope

Issue #983 asks for the next tool lane after #981 for `mnDiagram_SortNamesByKOs`.
The existing retained-frontier proof correctly identifies the remaining boundary,
but the implementation does not yet synthesize the broader natural C
equivalence classes needed to test that boundary.

This plan is intentionally limited to tooling. It should not change the retained
Melee source in `src/melee/mn/mndiagram.c`.

## Evidence reviewed

- Issue record: `melee-agent issue show 983`
- Capability audit:
  - `melee-agent capabilities search "sort source model synthesis loop selected slot GPR mwcc-debug"`
  - `melee-agent capabilities search "source model proof frontier synthesis coalesce search"`
- Retained-frontier artifact:
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_981_rerun/sort_frontiers/frontiers_all_sort.json`
- Source-model proof artifact:
  - `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_981_rerun/source_model_proofs/sort_source_model_terminal_proof.json`
- Main source and tool code:
  - `/Users/mike/code/melee/src/melee/mn/mndiagram.c`
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/registry.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
  - `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- Relevant tests:
  - `/Users/mike/code/melee/tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py`
  - `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`

The proof artifact reports:

- `status: terminal`
- `terminal_reason: post-ceiling-gpr-case-c-source-model-ceiling`
- forced physical targets: `IG34 -> r27`, `IG44 -> r25`
- only two post-ceiling source-model candidates were scored:
  - `post-ceiling-sort-init-pointer-walk`: `0/2`, with `IG34=r24`, `IG44=r27`
  - `post-ceiling-sort-swap-materialization`: `0/2`, with `IG34=r4`, `IG44=r31`
- suspect boundary: sort loop pointer progression and selected-slot address/copy materialization.

The retained-frontier artifact reports `all-known-frontiers-exhausted` and
`next_frontier: null`, so the next change belongs in source-model candidate
generation rather than retained-frontier triage.

## Root cause

`post_ceiling_baseline_escape.py` can name the source-model boundary, but it only
tests a narrow, hard-coded set of regex rewrites for this function.

For `mnDiagram_SortNamesByKOs`, `_add_sort_candidates` currently contributes
only three local candidate specs, and the terminal proof retained two scored
families:

- `_patch_sort_init_pointer_walk`, which only moves the `dst_iter++` and `tp++`
  increments from the `for` header into the loop body.
- `_patch_sort_swap_materialization`, which only splits `*(p += sizeof(...))`
  into a temporary selected-slot pointer and then reassigns `p`.

The later source-family discovery layer is also too shallow. The Sort dimensions
are single-probe dimensions such as `sort-init-indexed-write`,
`sort-indexed-byte-cache`, `sort-call-return-copy-local`, and
`sort-swap-slot-lvalue`. `_source_family_scores_close_terminal` treats that
single probe per dimension as enough to close the family, which allows a
terminal proof to be emitted before the broader natural C equivalence classes
have been explored.

This is why #983 is not a duplicate of #981: #981 closed retained-frontier and
local copy/source-owner families, while #983 needs a new source-model synthesis
layer that can generate, score, and terminalize a broader equivalence-class
space.

## Orchestrator amendment

After reviewing the artifacts in `mndiagram_970_rerun`,
`mndiagram_974_rerun`, and `mndiagram_981_rerun`, implement the issue's
explicitly allowed terminal-proof path first. The broader executable synthesis
lane already has partial machinery in `post_ceiling_baseline_escape.py`
(`post_ceiling_source_family_discovery` with four Sort dimensions), and prior
diagnostics show those broader source-family probes have been generated. The
current blocker is that `retained_frontier_triage.py` drops that synthesis
context from the source-model terminal proof, so matcher agents only see the
two local #981 candidates.

For this issue, make retained-frontier triage emit a stronger terminal proof
that:

- names the broader Sort source-family synthesis dimensions, including
  initialization indexed writes, indexed byte caching, call-return copy locals,
  and selected-slot lvalue materialization;
- preserves any `post_ceiling_source_family_discovery`,
  `post_ceiling_source_family_plateau_summary`, or
  `source_family_progress_plateau` data present in baseline-escape artifacts;
- records attempted equivalence classes, candidate IDs, scored candidate IDs,
  generated candidate IDs, source hunks, retained scored probes, skipped or
  missing dimensions, and the next unsupported source model;
- keeps older #981 artifacts working by deriving a conservative fallback
  synthesis model from the existing Sort candidate families when discovery data
  is absent.

Do not implement the full transform-corpus adapter in this pass. The terminal
proof should explicitly identify that adapter as the next unsupported source
model when all available broader source-family evidence still leaves IG34/IG44
at 0/2.

There is already reusable machinery for part of this space. The directed
transform corpus has `indexed_byte_address_temp_steering`, including variants
for indexed stores, init-loop splits, pointer aliases, base aliases, direct
global/dst stores, index temps, totals index temps, and max/current value temps.
Those probes are not currently integrated into the post-ceiling terminal lane.
The missing selected-slot movement variants around `p += sizeof(...)` are not
covered as broadly and should be added either as a focused transform-corpus
family or as a first-class post-ceiling source-model synthesis family.

## Desired behavior

When the retained post-ceiling Sort proof reaches the current local ceiling, the
tool should produce a bounded, deterministic list of executable C source
variants that cover broader natural C forms around:

- sorted-name initialization loop source form
- pointer progression versus indexed writes
- indexed byte reads in the selection loop
- selected-name slot address materialization
- selected-slot copy movement into `temp`, `p`, and `dst[i]`
- the `IG34` and `IG44` copy-product boundary

Each variant should be scored against `IG34 -> r27` and `IG44 -> r25` while
preserving normalized structural shape when possible.

If a variant improves either target, the lane should return an actionable ranked
candidate list instead of a terminal proof. If the bounded variant set is fully
scored and no target improvement appears, the terminal proof should explicitly
name the explored equivalence classes and the next unsupported source model.

## Implementation plan

### 1. Add a post-ceiling source-model synthesis layer

Implement the new layer in
`tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`, because this
module already owns:

- Sort source aliasing from `mnDiagram_SortNamesByKOs` to `mnDiagram_8023FC28`
- baseline-escape candidate generation
- source-family discovery summaries
- terminal summary emission consumed by retained-frontier triage
- `debug search baseline-escape --write-probes`

Add a focused summary builder, for example:

- `_post_ceiling_sort_source_model_synthesis_summary(...)`
- `_generate_sort_source_model_synthesis_candidates(...)`
- `_score_sort_source_model_synthesis_candidates(...)`

Trigger it only after the existing local post-ceiling Sort families are closed
or terminal, and only for the Sort function alias. Do not run it for unrelated
functions until it has a reusable configuration format.

Use a distinct family and terminal reason, for example:

- family: `post-ceiling-sort-source-model-synthesis`
- actionable status: `source-actionable`
- terminal kind: `post-ceiling-gpr-case-c-source-model-synthesis-proof`
- terminal reason: `post-ceiling-gpr-case-c-source-model-synthesis-exhausted`

Keep the old source-model terminal proof path working for old artifacts and for
functions without the new synthesis lane.

### 2. Reuse transform-corpus probes for initialization and byte-read forms

Add a small adapter from the post-ceiling synthesis layer to the directed
transform corpus instead of rebuilding those variants by hand.

Use existing transform families where possible:

- `indexed_byte_address_temp_steering`
- `ranked_cursor_iv_unification`
- `loop_index_pointer_walk_split`
- selected `counter_type_shape` variants if they produce natural init-loop
  source without destabilizing unrelated code

For the first implementation, keep the enabled set explicit and bounded for the
Sort function. Candidate classes should include at least:

- `init-loop-indexed-store`
- `init-loop-index-temp`
- `init-loop-pointer-alias`
- `init-loop-split`
- `direct-global-sorted-names-store`
- `direct-dst-sorted-names-store`
- `condition-index-alias`
- `totals-index-temp`
- `max-current-value-temp`

The adapter should:

- call the existing transform-corpus generation API with the Sort alias resolved
  to `mnDiagram_8023FC28`
- filter to candidates whose patch hunks intersect the initialization loop,
  selection comparison, or selected-slot movement region
- normalize candidate IDs into stable post-ceiling IDs
- deduplicate by full source hash and by changed-hunk signature
- record the originating transform family and mutator key in metadata

This directly addresses the audit-first requirement: the current corpus already
has much of the loop/source-form synthesis capability, but it is not wired into
the terminal post-ceiling proof lane.

### 3. Add selected-slot materialization equivalence variants

The selected-slot side is currently under-modeled. Add a focused set of natural
C rewrites for the block:

```c
u8* p = &assets->sorted_fighters[max_idx];
u8 temp = *(p += sizeof(mnDiagram_804A0750_t));
while (max_idx > i) {
    *p = *(p - 1);
    p--;
    max_idx--;
}
dst[i] = temp;
```

The generated variants should preserve the same source-level behavior and keep
the insertion movement intact. Candidate forms should include:

- direct selected source:
  - `u8 temp = dst[max_idx];`
  - `u8* p = &dst[max_idx];`
- selected pointer before load:
  - `u8* selected = dst + max_idx;`
  - `u8 temp = *selected;`
  - `u8* p = selected;`
- selected pointer through the asset struct:
  - `u8* selected = assets->sorted_names + max_idx;`
  - `u8 temp = *selected;`
  - `p = selected;`
- address first, temp second:
  - `p = &assets->sorted_names[max_idx];`
  - `temp = *p;`
- slot copy local:
  - `u8 selected_name = assets->sorted_names[max_idx];`
  - `temp = selected_name;`

Avoid variants that rewrite the algorithm from insertion movement to swap, or
that change which elements are shifted. This issue is about equivalent source
modeling for address/copy materialization, not changing algorithm structure.

Prefer implementing these as a small reusable mutator family if the transform
corpus API can express the needed anchors cleanly. If that is too invasive,
place them behind the new Sort-specific post-ceiling synthesis layer first and
leave a clear seam for later promotion into the transform corpus.

### 4. Rank candidates by target improvement and structural preservation

Extend the score interpretation in `post_ceiling_baseline_escape.py` so synthesis
candidates are ranked with a deterministic comparator:

1. number of target anchors matched for `IG34 -> r27` and `IG44 -> r25`
2. target virtual distance, lower first
3. normalized structural shape preserved
4. total match percentage, higher first
5. fewer unexpected spills around the target virtuals
6. smaller changed-hunk count
7. stable candidate ID

Expose the rank in the JSON summary, with per-candidate metadata:

- `candidate_id`
- `equivalence_class`
- `origin_family`
- `origin_mutator`
- `target_score`
- `target_virtuals`
- `structural_guard`
- `source_hash`
- `hunk_signature`
- `source_path` when files are materialized

If any candidate improves from `0/2` to `1/2` or `2/2`, report the synthesis
summary as actionable and do not emit a terminal proof.

### 5. Make terminal proof stronger when synthesis is exhausted

When all generated synthesis candidates have score payloads and none improves
the targets, emit a stronger terminal proof rather than the current two-probe
ceiling.

The proof should include:

- forced physical target map: `{34: 27, 44: 25}`
- prior local candidate IDs and their scores
- all synthesis candidate IDs and scores
- attempted equivalence classes
- deduped or skipped variants with reasons
- best candidate by rank, even if still `0/2`
- repeated prior candidates, so local retries are visible
- `next_unsupported_source_model`

Suggested wording for `next_unsupported_source_model`:

> No bounded equivalence-class rewrite around the retained initialization loop,
> selected-slot address materialization, or selected-slot copy movement improved
> IG34/IG44. The next unsupported model is an alternate natural C sort source
> structure outside the retained baseline assumptions, such as a different
> selection/insertion decomposition or a wider reordering of the comparison and
> slot-movement expressions.

Update `retained_frontier_triage.py` only after the richer summary exists. Its
job should remain proof extraction and reporting, not candidate generation.

### 6. Wire probe materialization through the existing CLI

Do not add a new top-level command for this issue. Extend the existing lane:

```bash
melee-agent debug search baseline-escape ...
```

When `--write-probes` is provided, write synthesis probes under a stable
subdirectory such as:

```text
<write-probes>/source-model-synthesis/
```

Each file should include:

- the complete executable source text
- metadata JSON or sidecar fields used by the existing probe writer
- the score-source command hint for the generated file
- family/equivalence-class information

Keep filenames stable and short enough for filesystem portability. Candidate IDs
should be deterministic so score artifacts can be joined back to summaries.

### 7. Update capability discovery

Update the capability brief/search metadata so future agents find this lane with
queries like:

```bash
melee-agent capabilities search "sort source model synthesis"
melee-agent capabilities search "IG34 IG44 selected slot"
```

The result should point to the existing `debug search baseline-escape` workflow
and mention source-model synthesis rather than suggesting a new tool.

## Regression tests

### Post-ceiling synthesis generation

Add tests in:

```text
/Users/mike/code/melee/tools/melee-agent/tests/test_post_ceiling_baseline_escape.py
```

Create a fixture based on the existing `_sort_source` and the current proof
conditions:

- retained continuation closed
- old local candidates scored `0/2`
- final force map `{34: 27, 44: 25}`

Assert that `generate_baseline_escape_candidates(...)` now produces a
`post-ceiling-sort-source-model-synthesis` summary with `status:
source-actionable` when synthesis candidates have not yet been scored.

Assertions:

- candidate count is greater than the two old proof candidates
- candidate metadata includes both loop-source and selected-slot equivalence
  classes
- generated IDs are stable
- generated source hashes are unique
- the old `post-ceiling-sort-init-pointer-walk` and
  `post-ceiling-sort-swap-materialization` sources are not repeated as new
  synthesis candidates
- validation metadata contains the `IG34 -> r27` and `IG44 -> r25` targets

### Probe materialization

Extend the existing write-probes test in
`test_post_ceiling_baseline_escape.py`.

Assert that `generate_baseline_escape_candidate_files(...)` writes synthesis
files under `source-model-synthesis/` and that each materialized file:

- contains the full `mnDiagram_8023FC28` source
- includes the candidate ID in metadata
- includes a usable `debug target score-source` command hint
- has a stable relative path suitable for later score artifact joins

### Ranking with target improvement

Add a scoring test with fake score payloads for synthesis candidates.

Use at least three candidates:

- one still `0/2`
- one matching `IG34 -> r27`
- one matching `IG44 -> r25` but with worse structural guard or distance

Assert that:

- the summary is actionable, not terminal
- the improving candidate ranks first according to the comparator
- per-candidate target details include expected and actual physical registers
- structural preservation affects tie-breaking but does not hide target
  improvement

### Exhausted synthesis terminal proof

Add a test where every generated synthesis candidate has a score payload and all
remain `0/2`.

Assert that:

- the emitted terminal kind is
  `post-ceiling-gpr-case-c-source-model-synthesis-proof`
- the terminal reason is
  `post-ceiling-gpr-case-c-source-model-synthesis-exhausted`
- the proof lists all attempted equivalence classes
- prior local proof candidates are retained as prior evidence
- skipped/deduped variants are reported
- `next_unsupported_source_model` is non-empty and specifically says the next
  source model is outside current retained baseline assumptions

### Retained-frontier proof extraction

Add tests in:

```text
/Users/mike/code/melee/tools/melee-agent/tests/test_retained_frontier_triage.py
```

Keep the existing old-artifact test passing. Add a new fixture representing the
synthesis-exhausted summary and assert that retained-frontier triage extracts a
terminal proof with:

- candidate count greater than two
- attempted equivalence classes
- the forced target map
- the new terminal reason
- the stronger unsupported-source-model text

### Transform-corpus selected-slot variants

If selected-slot variants are implemented in the transform corpus, add tests in:

```text
/Users/mike/code/melee/tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py
```

or a new focused transform-corpus test file.

Assert that the `p += sizeof(mnDiagram_804A0750_t)` pattern generates selected
slot probes that:

- preserve the `while (max_idx > i)` movement loop
- preserve `dst[i] = temp`
- do not rewrite the algorithm into a swap
- reject non-matching pointer-update patterns
- include origin metadata for the selected-slot materialization class

### CLI smoke

Add or extend a CLI smoke test for:

```bash
melee-agent debug search baseline-escape --write-probes <tmpdir> --json ...
```

Use fixture score/evidence JSON rather than invoking the compiler. Assert that
the JSON contains the synthesis summary and that the probe files are written.

### Capability search

Add a capability test so:

```bash
melee-agent capabilities search "sort source model synthesis"
```

returns the baseline-escape/source-model synthesis lane.

## Manual validation

After implementing the tool changes, run:

```bash
python -m pytest tools/melee-agent/tests/test_post_ceiling_baseline_escape.py
python -m pytest tools/melee-agent/tests/test_retained_frontier_triage.py
python -m pytest tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py
python -m pytest tools/melee-agent/tests/search -k "baseline_escape or source_model or capability"
```

Then regenerate the Sort probes from the current artifact set:

```bash
melee-agent debug search baseline-escape \
  --function mnDiagram_SortNamesByKOs \
  --write-probes build/diagnostics/mndiagram_983/source_model_synthesis \
  --json
```

Score the emitted files with the existing scorer:

```bash
melee-agent debug target score-source \
  --function mnDiagram_SortNamesByKOs \
  --source <candidate.c> \
  --force-phys 34:27 \
  --force-phys 44:25 \
  --json
```

Finally rerun retained-frontier triage against the new score artifacts and
confirm one of two outcomes:

- an actionable ranked candidate improves either `IG34` or `IG44`; or
- the terminal proof now names every attempted equivalence class and the next
  unsupported source model, rather than stopping at the two local candidates.

## Risks and guardrails

- Regex-only patchers are brittle. Keep all new source rewrites guarded by exact
  function aliases, exact source neighborhoods, and source hash or hunk
  signatures where possible.
- Candidate explosion is possible if the whole transform corpus is enabled.
  Start with an explicit Sort allowlist and a deterministic cap.
- Do not mark synthesis exhausted when generated candidates are unscored. The
  lane should be actionable until every candidate in the bounded set has a
  joined score payload.
- Do not relax structural preservation enough to hide algorithm changes. The
  variants should remain source-equivalent rewrites around loop shape and slot
  materialization.
- Keep retained-frontier triage as a summarizer. Candidate generation belongs in
  the post-ceiling/source-model lane.

## Definition of done

- `debug search baseline-escape` can emit broader Sort source-model synthesis
  probes after the current local proof ceiling.
- The emitted probes include loop-source and selected-slot equivalence classes.
- Score artifacts for those probes are ranked against `IG34 -> r27` and
  `IG44 -> r25`.
- Improved target scores are reported as actionable candidates.
- Fully exhausted bounded exploration emits a stronger terminal proof naming the
  unsupported source model.
- Regression tests cover generation, materialization, scoring/ranking,
  exhaustion proof extraction, selected-slot variants, CLI behavior, and
  capability discovery.
