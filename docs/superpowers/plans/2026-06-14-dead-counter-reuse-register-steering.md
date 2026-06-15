# Dead Counter Reuse Register Steering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded `steer_reuse_dead_top_level_loop_counter` transform-corpus probe that appears in default-budget `coloring_register_steering` output for `mnDiagram2_Create`.

**Architecture:** Reuse the existing direct register-steering analyzer in `transform_corpus.py` and the exact-span replacement pattern in `mutators.py`. The new analyzer emits one contiguous span from the removable later-counter declaration through the selected later loop, with conservative identifier guards before any candidate is materialized.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `src.search.directed` transform-corpus helpers.

---

### Task 1: Add Failing Regression Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [ ] **Step 1: Add metadata expectation**

In `test_coloring_register_steering_metadata_is_executable()`, add the new key after `steer_demote_local_decl_to_first_use` and before `steer_split_reused_loop_counter`:

```python
        "steer_reuse_dead_top_level_loop_counter",
```

- [ ] **Step 2: Add exact-span mutator test**

Append this test to `tools/melee-agent/tests/search/directed/test_mutators.py` near the other concrete steering mutator tests:

```python
def test_steer_reuse_dead_top_level_loop_counter_validates_exact_span() -> None:
    src = (
        "void f(void) {\n"
        "    int j;\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j);\n"
        "        j++;\n"
        "    } while (j < 2);\n"
        "}\n"
    )
    span_text = (
        "    int j;\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j);\n"
        "        j++;\n"
        "    } while (j < 2);"
    )
    replacement_text = (
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    i = 0;\n"
        "    do {\n"
        "        sink(i);\n"
        "        i++;\n"
        "    } while (i < 2);"
    )
    start = src.index(span_text)
    anchor = Anchor(
        "steer_reuse_dead_top_level_loop_counter",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement_text},
    )

    assert apply_mutator("steer_reuse_dead_top_level_loop_counter", anchor, src) == (
        "void f(void) {\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    i = 0;\n"
        "    do {\n"
        "        sink(i);\n"
        "        i++;\n"
        "    } while (i < 2);\n"
        "}\n"
    )
```

- [ ] **Step 3: Extend stale-span rejection**

In `test_concrete_steering_mutators_reject_stale_spans()`, include:

```python
        "steer_reuse_dead_top_level_loop_counter",
```

- [ ] **Step 4: Add default-budget generation test**

Add or update a `coloring_register_steering` generation test with this source shape:

```python
source = (
    "void mnDiagram2_Create(s32* a, s32 seed) {\n"
    "    s32 temp;\n"
    "    HSD_GObj* gobj;\n"
    "    int j;\n"
    "    int i;\n"
    "    temp = seed;\n"
    "    for (i = 0; i < 3; i++) {\n"
    "        sink(a[i]);\n"
    "    }\n"
    "    j = 0;\n"
    "    do {\n"
    "        sink(j, temp, gobj);\n"
    "        j++;\n"
    "    } while (j < 2);\n"
    "}\n"
)
```

Assert the default-budget concrete keys are:

```python
assert [probe.mutator_key for probe in steering] == [
    "steer_rotate_local_decl_window",
    "steer_demote_local_decl_to_first_use",
    "steer_reuse_dead_top_level_loop_counter",
]
assert "int j;" not in steering[2].candidate_text
assert "i = 0;" in steering[2].candidate_text
assert "sink(i, temp, gobj);" in steering[2].candidate_text
assert "} while (i < 2);" in steering[2].candidate_text
```

- [ ] **Step 5: Add unsafe generation cases**

Extend `test_coloring_register_steering_rejects_unsafe_concrete_levers()` or add a dedicated test that asserts no `steer_reuse_dead_top_level_loop_counter` is emitted for:

```python
unsafe_sources = {
    "old counter used in later loop": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(i, j);\n        j++;\n    } while (j < 2);\n}\n",
    "later counter used before prelude": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    sink(j);\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "either counter used after later loop": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n    sink(i, j);\n}\n",
    "counter in comment": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j); // i must not be rewritten here\n        j++;\n    } while (j < 2);\n}\n",
    "member access": "void mnDiagram2_Create(Holder* obj) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(obj->i, j);\n        j++;\n    } while (j < 2);\n}\n",
    "statement between prelude and do": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    sink(0);\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "nested shadow": "void mnDiagram2_Create(void) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        int i;\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "return barrier between loops": "void mnDiagram2_Create(int flag) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    if (flag) {\n        return;\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "goto barrier between loops": "void mnDiagram2_Create(int flag) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    if (flag) {\n        goto done;\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n    done:\n    return;\n}\n",
    "switch barrier between loops": "void mnDiagram2_Create(int flag) {\n    int j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    switch (flag) {\n    case 0:\n        sink(0);\n        break;\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "initialized old counter": "void mnDiagram2_Create(void) {\n    int j;\n    int i = 0;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "initialized later counter": "void mnDiagram2_Create(void) {\n    int j = 0;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "mismatched counter types": "void mnDiagram2_Create(void) {\n    s32 j;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
    "multi declarator later counter": "void mnDiagram2_Create(void) {\n    int j, k;\n    int i;\n    for (i = 0; i < 3; i++) {\n        sink(i);\n    }\n    j = 0;\n    do {\n        sink(j);\n        j++;\n    } while (j < 2);\n}\n",
}
```

For each source, run `generate_transform_probes(...)` and assert:

```python
assert "steer_reuse_dead_top_level_loop_counter" not in {
    probe.mutator_key for probe in probes
}
```

- [ ] **Step 6: Lock loop-order pairing**

Add a generation test where two earlier dead top-level loop counters and two later counters are all eligible:

```c
void mnDiagram2_Create(void) {
    int k;
    int j;
    int h;
    int i;
    for (i = 0; i < 3; i++) {
        sink(i);
    }
    for (h = 0; h < 3; h++) {
        sink(h);
    }
    j = 0;
    do {
        sink(j);
        j++;
    } while (j < 2);
    k = 0;
    do {
        sink(k);
        k++;
    } while (k < 2);
}
```

With `max_per_family` high enough to expose all candidates, assert the first `steer_reuse_dead_top_level_loop_counter` candidate reuses `i` for `j` and does not jump to `h` or `k`. This locks pairing by source loop order, not declaration order.

- [ ] **Step 7: Update CLI smoke expectations**

In `test_search_plan_transforms_writes_concrete_coloring_register_steering_probes()`, update the fixture so it contains the dead-counter shape and assert the third emitted key is `steer_reuse_dead_top_level_loop_counter`.

- [ ] **Step 8: Run focused tests and verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'coloring_register_steering or dead_top_level_loop_counter or source_transform_catalog'
```

Expected before implementation: failures mentioning missing key, unknown mutator, or missing candidate.

### Task 2: Implement Exact-Span Mutator And Metadata

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [ ] **Step 1: Add mutator wrapper**

In `mutators.py`, add:

```python
def _steer_reuse_dead_top_level_loop_counter(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one exact later loop region to reuse a dead earlier counter."""
    return _replace_validated_span(anchor, source_text)
```

Register it in `_DISPATCH`:

```python
    "steer_reuse_dead_top_level_loop_counter": _steer_reuse_dead_top_level_loop_counter,
```

- [ ] **Step 2: Update family metadata**

In `transform_corpus.py`, add the key to `coloring_register_steering.mutator_keys` after `steer_demote_local_decl_to_first_use`:

```python
            "steer_reuse_dead_top_level_loop_counter",
```

Add it to `_DIRECT_REGISTER_STEERING_KEYS`:

```python
    "steer_reuse_dead_top_level_loop_counter",
```

- [ ] **Step 3: Update catalog metadata**

In `source_transform_catalog.py`, add the key to the directed mutator key set/list for transform-corpus. Update docs counts in `docs/source-transform-catalog.md` by adding one concrete directed mutator key.

- [ ] **Step 4: Run focused tests**

Run the focused command from Task 1. Expected after metadata/mutator registration: only generator-related tests should still fail.

### Task 3: Implement Dead-Counter Anchor Generation

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Add loop model dataclasses**

Near `_RegisterSteeringLoop`, add a model for selected later loops:

```python
@dataclass(frozen=True)
class _RegisterSteeringDeadCounterLoop:
    start: int
    end: int
    counter: str
    kind: str
    prelude_start: int
    body_start: int
    idx: int
```

For `for` loops, `prelude_start` equals `start`. For `do` loops, `prelude_start` is the top-level `counter = init;` assignment line start. Emit `do`-prelude candidates before simple later-`for` candidates, with source order preserved within each group.

- [ ] **Step 2: Add helper predicates**

Implement helpers that use existing `_blank_literals_and_comments()`, `_identifier_mentions()`, `_raw_identifier_spans()`, `_identifier_is_member_name()`, `_macro_like_statement()`, `_line_has_label()`, and line-depth helpers:

```python
def _register_steering_counter_decl(decls, name):
    matches = [
        decl for decl in decls
        if decl.depth == 1
        and decl.name == name
        and not decl.init
        and decl.type_name in {"int", "s32", "u32", "s16", "u16"}
    ]
    return matches[0] if len(matches) == 1 else None

def _counter_region_rejects(searchable: str, raw: str, *names: str) -> bool:
    if "#" in searchable or re.search(
        r"\b(?:return|goto|switch|case|default|break|continue)\b",
        searchable,
    ):
        return True
    for _start, _end, line in _text_line_records(searchable):
        if _line_has_label(line) or _macro_like_statement(line):
            return True
    for name in names:
        if re.search(r"&\s*" + re.escape(name) + r"\b", searchable):
            return True
        for start, _end in _identifier_mentions(searchable, name):
            if _identifier_is_member_name(searchable, start):
                return True
        if set(_raw_identifier_spans(raw, name)) != set(_identifier_mentions(searchable, name)):
            return True
    return False
```

- Use the identifier portion of this check for the full exact span, so
  comments/string literals and address-takes of the counters are still rejected
  without rejecting unrelated setup calls that are preserved and not rewritten.
- Use the full barrier check for the earlier loop, selected later prelude/loop,
  and the region between those loops.

- [ ] **Step 3: Detect top-level `do` loops with immediate prelude**

Add a helper that scans line records and returns `_RegisterSteeringDeadCounterLoop` for this shape:

```c
    j = 0;
    do {
        ...
        j++;
    } while (j < 10);
```

Rules:
- the assignment line and `do {` are both depth 1,
- only blank or comment-only lines may appear between them,
- the `do` block must balance back to depth 1,
- the `while (...) ;` close line must mention the same counter,
- the body/header must contain the later counter and no old counter before rewrite.

- [ ] **Step 4: Implement `_iter_dead_top_level_loop_counter_reuse_anchors()`**

Algorithm:

```python
def _iter_dead_top_level_loop_counter_reuse_anchors(body_text: str, decls: tuple[_RegisterSteeringDecl, ...]) -> list[Anchor]:
    searchable = _blank_literals_and_comments(body_text)
    loops = list(_register_steering_loop_blocks(body_text))
    later_loops = list(_register_steering_dead_counter_later_loops(body_text))
    anchors = []
    for earlier in loops:
        old_decl = _register_steering_counter_decl(decls, earlier.counter)
        if old_decl is None:
            continue
        for later in later_loops:
            if later.start <= earlier.end or later.counter == earlier.counter:
                continue
            later_decl = _register_steering_counter_decl(decls, later.counter)
            if later_decl is None or later_decl.type_name != old_decl.type_name:
                continue
            span_start = later_decl.start
            span_end = later.end
            span_text = body_text[span_start:span_end]
            searchable_span = searchable[span_start:span_end]
            if body_text.count(span_text) != 1:
                continue
            if _counter_identifier_region_rejects(searchable_span, span_text, earlier.counter, later.counter):
                continue
            between = searchable[earlier.end:later.prelude_start]
            if _identifier_mentions(between, earlier.counter):
                continue
            before_later_region = searchable[later_decl.end_with_newline:later.prelude_start]
            if _identifier_mentions(before_later_region, later.counter):
                continue
            after_later = searchable[later.end:]
            if _identifier_mentions(after_later, earlier.counter) or _identifier_mentions(after_later, later.counter):
                continue
            if _has_duplicate_or_nested_counter_decl(decls, earlier.counter, later.counter):
                continue
            replacement = body_text[span_start:span_end]
            replacement = _remove_exact_line(replacement, later_decl.line)
            replacement = _replace_identifier_spans_in_later_region(
                replacement,
                later.counter,
                earlier.counter,
                later_region_offsets,
            )
            anchors.append(Anchor(...))
    return anchors
```

The generator owns all semantic analysis and replacement construction: it removes the later declaration and rewrites only identifier spans in the selected later loop/prelude. The mutator remains intentionally dumb and only applies `_replace_validated_span()` against the exact payload. Use local span arithmetic rather than global string replacement for identifier rewrites. The implementation should only rewrite spans from blanked text after proving raw spans match, so comments/literals are rejected.

- [ ] **Step 5: Interleave into concrete steering order**

In `_iter_concrete_register_steering_body_anchors()`, compute:

```python
reuse_dead = _iter_dead_top_level_loop_counter_reuse_anchors(body_text, decls)
```

and yield:

```python
yield from _interleave_anchor_groups(rotate, demote, reuse_dead, split)
```

This makes the real candidate visible under `max_per_family=3` when present.

- [ ] **Step 6: Run focused tests**

Run the focused pytest command from Task 1. Expected: all focused tests pass.

### Task 4: Command-Level Verification

**Files:**
- No production edits expected.

- [ ] **Step 1: Run broader affected suite**

Run:

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

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run installed CLI materialization smoke**

After refreshing editable install, run:

```bash
tmpdir=$(mktemp -d build/mwcc_debug_cache/dead-counter-probes.XXXXXX)
/opt/homebrew/bin/melee-agent debug search plan-transforms \
  --function mnDiagram2_Create \
  --unit melee/mn/mndiagram2 \
  --force-phys 58:4,35:29 \
  --max-per-family 3 \
  --write-probes "$tmpdir" \
  --json
```

Expected: JSON probes include `steer_reuse_dead_top_level_loop_counter` and the candidate file exists.

- [ ] **Step 4: Run real validation smoke**

Run:

```bash
tmpdir=$(mktemp -d build/mwcc_debug_cache/dead-counter-validate.XXXXXX)
/opt/homebrew/bin/melee-agent debug search plan-transforms \
  --function mnDiagram2_Create \
  --unit melee/mn/mndiagram2 \
  --force-phys 58:4,35:29 \
  --max-per-family 3 \
  --write-probes "$tmpdir" \
  --validate-command "/opt/homebrew/bin/melee-agent debug dump local {candidate_path} --unit-source src/melee/mn/mndiagram2.c --function mnDiagram2_Create --diff --no-cache-sync" \
  --json
```

Expected: validation runs the dead-counter candidate. If any candidate byte-matches, resolve #699. If all compile but remain negative evidence, note that #699's stop condition remains unmet and release the claim.

### Task 5: Finalize

**Files:**
- Modify: `/Users/mike/.codex/automations/issue-resolver/memory.md`

- [ ] **Step 1: Commit implementation**

Run:

```bash
git add \
  docs/source-transform-catalog.md \
  docs/superpowers/plans/2026-06-14-dead-counter-reuse-register-steering.md \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py
git commit -m "Add dead counter register steering probe"
```

- [ ] **Step 2: Refresh editable install**

Run:

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/opt/python@3.11/bin/python3.11 - <<'PY'
import src, src.launcher
print(src.__file__)
print(src.launcher.__file__)
PY
```

Expected: imports point at `/Users/mike/code/melee/tools/melee-agent`.

- [ ] **Step 3: Resolve or release #699**

If validation produced a byte match:

```bash
melee-agent issue resolve 699 --note "fixed in <commit>: dead-counter reuse register-steering candidate reaches byte_match"
```

If validation did not produce a byte match:

```bash
melee-agent issue note 699 --body "Implemented steer_reuse_dead_top_level_loop_counter in <commit>; candidate materializes under default budget and validation result was <summary>. Leaving open because byte_match stop condition remains unmet."
melee-agent issue release 699
```

- [ ] **Step 4: Update memory and final status**

Append a concise entry to `/Users/mike/.codex/automations/issue-resolver/memory.md` with:
- issue handled,
- commit hash,
- validation commands and results,
- whether #699 was resolved or left open,
- editable install path,
- final `git status --short --branch`.
