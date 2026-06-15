# Register-Steering Concrete Levers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add guarded concrete register-steering probes for declaration-window rotation, declaration demotion, and reused loop-counter splitting under `coloring_register_steering`.

**Architecture:** Keep `coloring_register_steering` as the planner family for mndiagram force-phys residuals. Add exact-span mutators and a steering-only target-body analyzer that abstains on ambiguous C shapes, then feed candidates through the existing transform-corpus probe and scoring pipeline.

**Tech Stack:** Python 3.11, pytest, `src.search.directed.transform_corpus`, `src.search.directed.mutators`, existing transform-corpus CLI tests.

---

### Task 1: Red Tests For Concrete Steering Levers

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [x] Update `test_coloring_register_steering_metadata_is_executable()` to expect these additional keys at the end of `mutator_keys`:

```python
"steer_rotate_local_decl_window",
"steer_demote_local_decl_to_first_use",
"steer_split_reused_loop_counter",
```

- [x] Add mutator unit tests:

```python
def test_steer_rotate_local_decl_window_validates_exact_span() -> None:
    src = "void f(void) {\n    s32 a;\n    s32 b;\n    HSD_GObj* gobj;\n}\n"
    span_text = "    s32 a;\n    s32 b;\n    HSD_GObj* gobj;"
    start = src.index(span_text)
    anchor = Anchor(
        "steer_rotate_local_decl_window",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "    HSD_GObj* gobj;\n    s32 a;\n    s32 b;",
        },
    )
    assert apply_mutator("steer_rotate_local_decl_window", anchor, src) == (
        "void f(void) {\n    HSD_GObj* gobj;\n    s32 a;\n    s32 b;\n}\n"
    )


def test_steer_demote_local_decl_to_first_use_validates_exact_span() -> None:
    src = "void f(void) {\n    s32 temp;\n    s32 rank;\n    rank = seed + 1;\n    temp = rank;\n}\n"
    span_text = "    s32 temp;\n    s32 rank;\n    rank = seed + 1;\n    temp = rank;"
    start = src.index(span_text)
    replacement = "    s32 rank;\n    rank = seed + 1;\n    s32 temp;\n    temp = rank;"
    anchor = Anchor(
        "steer_demote_local_decl_to_first_use",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement},
    )
    assert apply_mutator("steer_demote_local_decl_to_first_use", anchor, src) == (
        "void f(void) {\n"
        "    s32 rank;\n"
        "    rank = seed + 1;\n"
        "    s32 temp;\n"
        "    temp = rank;\n"
        "}\n"
    )


def test_steer_split_reused_loop_counter_validates_exact_span() -> None:
    src = (
        "void f(s32* a, s32* b) {\n"
        "    s32 i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(b[i]);\n"
        "    }\n"
        "}\n"
    )
    span_text = "    for (i = 0; i < 2; i++) {\n        sink(b[i]);\n    }"
    start = src.index(span_text)
    replacement = "    s32 i_1;\n    for (i_1 = 0; i_1 < 2; i_1++) {\n        sink(b[i_1]);\n    }"
    anchor = Anchor(
        "steer_split_reused_loop_counter",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement},
    )
    assert apply_mutator("steer_split_reused_loop_counter", anchor, src) == src.replace(span_text, replacement, 1)
```

- [x] Add stale-span tests for all three mutators by changing the source text and asserting `apply_mutator(...) is None`.
- [x] Add a positive probe-generation test for mndiagram:

```python
def test_coloring_register_steering_materializes_concrete_levers() -> None:
    source = (
        "void mnDiagram2_Create(s32* a, s32* b, s32 seed) {\n"
        "    s32 temp;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    rank = seed + 1;\n"
        "    temp = rank;\n"
        "    use(gobj, temp);\n"
        "    s32 i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(b[i]);\n"
        "    }\n"
        "}\n"
    )
    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=3,
    )
    steering = [probe for probe in probes if probe.family_id == "coloring_register_steering"]
    assert {
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
        "steer_split_reused_loop_counter",
    } <= {probe.mutator_key for probe in steering}
    assert any("HSD_GObj* gobj;\n    s32 temp;\n    s32 rank;" in p.candidate_text for p in steering)
    assert any("s32 temp;\n    temp = rank;" in p.candidate_text for p in steering)
    assert any("s32 i_1;\n    for (i_1 = 0; i_1 < 2; i_1++)" in p.candidate_text for p in steering)
```

- [x] Add rejection cases under one parameterized test that assert none of the three new mutator keys appear for:
  - preprocessor-bearing body,
  - initialized declaration window,
  - qualified declaration window,
  - aggregate-by-value declaration such as `Vec3 pos;`,
  - duplicate exact declaration window,
  - declaration demotion across a label, goto, macro-looking statement, or nested block,
  - nested loop reuse,
  - counter use after the selected later loop,
  - address-take of the reused counter,
  - generated split name collision.
- [x] Add CLI smoke in `test_search_plan_transforms_writes_coloring_register_steering_probes()` or a new test using `plan-transforms --function mnDiagram2_Create --unit melee/mn/mndiagram2 --force-phys 58:4,35:29 --source-file fixture.c --max-per-family 3 --write-probes --json`, asserting candidate files exist for the three new mutator keys. This verifies default-budget visibility rather than only high-cap behavior.
- [x] Update source-transform catalog count tests to expect three additional directed mutator keys.
- [x] Run focused tests and confirm they fail for missing mutators/analyzers:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'coloring_register_steering or rotate_local_decl_window or demote_local_decl or split_reused_loop_counter or source_transform_catalog'
```

### Task 2: Exact-Span Mutators And Catalog Wiring

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [x] Add a shared helper if not already available:

```python
def _replace_validated_span(anchor: Anchor, source_text: str) -> Optional[str]:
    start, end = anchor.span
    span_text = anchor.payload.get("span_text")
    replacement_text = anchor.payload.get("replacement_text")
    if not isinstance(span_text, str) or not isinstance(replacement_text, str):
        return None
    if start < 0 or end < start or end > len(source_text):
        return None
    if source_text[start:end] != span_text:
        return None
    return source_text[:start] + replacement_text + source_text[end:]
```

If a helper with this behavior already exists, reuse it instead of adding a duplicate.
- [x] Add mutator functions:

```python
def _steer_rotate_local_decl_window(anchor: Anchor, source_text: str) -> Optional[str]:
    return _replace_validated_span(anchor, source_text)


def _steer_demote_local_decl_to_first_use(anchor: Anchor, source_text: str) -> Optional[str]:
    return _replace_validated_span(anchor, source_text)


def _steer_split_reused_loop_counter(anchor: Anchor, source_text: str) -> Optional[str]:
    return _replace_validated_span(anchor, source_text)
```

- [x] Register the three keys in `_DISPATCH`.
- [x] Add the three keys to `coloring_register_steering.mutator_keys`.
- [x] Add the three keys to `DIRECTED_MUTATOR_KEYS`.
- [x] Update source-transform catalog docs and counts.
- [x] Run mutator/catalog focused tests. Expected: mutator and metadata tests pass; probe-generation tests still fail until analyzers exist.

### Task 3: Steering Analyzer

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [x] Extend `_iter_register_steering_body_anchors(body_text)` rather than adding a second steering loop. Keep the existing preprocessor barrier.
- [x] Represent top-level declaration records with start/end/line/type/name/init/depth using the existing `_register_steering_decl_match()`.
- [x] Add a supported declaration-type predicate for these new concrete levers. Allow explicit scalar integer/float spellings (`char`, `s8`, `u8`, `short`, `s16`, `u16`, `int`, `s32`, `u32`, `long`, `float`, `f32`) and pointer declarations containing `*`; reject aggregate-by-value typedefs such as `Vec3 pos;`.
- [x] Add `rotate_local_decl_window` anchors:
  - only contiguous windows of three top-level declarations,
  - all uninitialized,
  - exact `span_text` appears once,
  - replacement is last line plus first two lines,
  - payload includes `span_text`, `replacement_text`, `strategy: "decl-window-rotate"`, and `decl_names`.
- [x] Add demotion anchors:
  - select contiguous runs of uninitialized, supported top-level declarations,
  - keep the replacement entirely inside that declaration prologue so probes remain MWCC/C89-safe,
  - require the declaration run text to be unique,
  - replacement removes one declaration from its original position and appends it to the tail of the same declaration run,
  - payload includes `strategy: "decl-demote-within-prologue"`, `decl_name`, `span_text`, and `replacement_text`.
- [x] Add reused-loop-counter split anchors:
  - parse top-level `for (<name> = ...; ...; <name>++) { ... }` blocks with balanced braces,
  - require one previous loop with the same counter before the selected loop,
  - require the counter declaration type to be `int`, `s32`, `u32`, `s16`, or `u16`,
  - generate `<name>_1`, `<name>_2`, etc. without colliding with existing identifiers,
  - reject selected loop text containing `&name`, `break`, `continue`, `goto`, labels, or preprocessor lines,
  - reject uses after the selected loop,
  - replacement declares the fresh counter immediately after the original counter declaration and rewrites identifier mentions in the selected loop,
  - payload includes `strategy: "split-reused-loop-counter"`, `original_counter`, `fresh_counter`, `counter_type`, `span_text`, and `replacement_text`.
- [x] Interleave/prioritize steering probes so the new concrete keys are emitted before older alias keys for `coloring_register_steering`. With default `max_per_family=3`, a fixture containing all three concrete levers must emit exactly those three mutator keys; alias probes may appear only when the budget is larger.
- [x] Run focused transform-corpus tests until green.

### Task 4: Verification, Review, Commit

**Files:**
- Review all changed files.

- [x] Run focused tests:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'coloring_register_steering or rotate_local_decl_window or demote_local_decl or split_reused_loop_counter or source_transform_catalog'
```

- [x] Run broader directed-search affected suite:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_coalesce_search.py \
  tools/melee-agent/tests/test_select_order_search.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_frame_transform_search.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/directed/test_scorer.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

- [x] Run static checks:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

- [x] Run command-level smoke through `/opt/homebrew/bin/melee-agent debug search plan-transforms --function mnDiagram2_Create --unit melee/mn/mndiagram2 --force-phys 58:4,35:29 --source-file <fixture> --max-per-family 3 --write-probes <tmp> --json` and confirm all three new mutator keys appear.
- [x] Request independent implementation review. Fix blockers and rerun affected tests.
- [x] Commit spec, plan, docs, tests, and implementation.
- [x] Refresh editable install from `/Users/mike/code/melee/tools/melee-agent`, verify import path, run installed CLI smoke, and either resolve #699 if byte-match/search evidence is sufficient or release it with a note describing the remaining evidence gap.

### Verification Notes

- Focused regressions: `33 passed, 333 deselected`.
- Broader affected suite: `619 passed`.
- Static checks: `compileall` on changed Python modules and `git diff --check`.
- CLI smoke: `/opt/homebrew/bin/melee-agent debug search plan-transforms --function mnDiagram2_Create --unit melee/mn/mndiagram2 --force-phys 58:4,35:29 --max-per-family 3 --write-probes --json` emitted `steer_rotate_local_decl_window`, `steer_demote_local_decl_to_first_use`, and `steer_split_reused_loop_counter`.
- Independent implementation review found two blocking safety gaps; both were fixed with regressions for member/literal/comment loop-counter hazards and unbraced-control demotion barriers.
