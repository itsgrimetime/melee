# Same-Type Local Lifetime Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add guarded executable `same_type_local_lifetime_reuse` transform-corpus probes for simple scalar and pointer locals with non-overlapping lifetimes.

**Architecture:** Reuse the existing `Anchor` and `apply_mutator` pipeline. The target-function analysis lives in `tools/melee-agent/src/search/directed/transform_corpus.py`; the exact scoped replacement mutator lives in `tools/melee-agent/src/search/directed/mutators.py`; catalog metadata and docs are updated in the existing source-transform catalog files.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules, `src.mwcc_debug.source_patch.find_function`.

---

### Task 1: Red Tests For Metadata, Probes, And Mutator

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [ ] **Step 1: Update metadata expectations**

Change `test_same_type_local_lifetime_reuse_is_record_only_until_lifetime_analysis_exists` into an executable-family assertion:

```python
def test_same_type_local_lifetime_reuse_metadata_is_executable() -> None:
    family = next(
        family
        for family in DEFAULT_TRANSFORM_FAMILIES
        if family.family_id == "same_type_local_lifetime_reuse"
    )

    assert family.mutator_keys == ("reuse_same_type_local_lifetime",)
    assert family.semantic_risk == "medium"
    assert "same-type local declarations" in family.source_region_selector
    assert "reduce local count" in family.expected_compiler_effect
    assert "record-only" not in family.generated_probe_form
    assert {"same-type", "lifetime", "reuse", "cur", "prev"} <= set(family.keywords)
```

Update catalog tests to expect `summary["concrete_forms"] == 81`, `entry.concrete_form_count == 28`, and `"reuse_same_type_local_lifetime" in DIRECTED_MUTATOR_KEYS`.

- [ ] **Step 2: Add positive probe fixtures**

Add a helper:

```python
def _same_type_reuse_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("same_type_local_lifetime_reuse",),
        max_per_family=max_per_family,
    )
```

Add the pointer fixture:

```c
typedef struct ItemLink ItemLink;
struct ItemLink { ItemLink* next; int pos; };
static ItemLink* it_802BCB88_prev(ItemLink* link);
void target(ItemLink* link) {
    ItemLink* cur;
    ItemLink* prev;

    cur = link->next;
    if (cur != NULL) {
        use(cur);
    }

    prev = it_802BCB88_prev(link);
    if (prev != NULL) {
        use(prev->pos);
    }
}
```

Assert the candidate removes `ItemLink* prev;`, contains `cur = it_802BCB88_prev(link);`, contains `if (cur != NULL)`, contains `use(cur->pos);`, and preserves the helper name. Assert:

```python
assert probe.family_id == "same_type_local_lifetime_reuse"
assert probe.mutator_key == "reuse_same_type_local_lifetime"
assert probe.probe_id == "same_type_local_lifetime_reuse@0"
assert transform_probe_key(probe) == "transform-corpus:same_type_local_lifetime_reuse:0"
assert probe.payload["reused_name"] == "cur"
assert probe.payload["original_name"] == "prev"
assert probe.payload["local_type"] == "ItemLink*"
assert probe.payload["replacement_count"] == 3
assert isinstance(probe.payload["reused_decl_span"], tuple)
assert isinstance(probe.payload["original_decl_span"], tuple)
```

Add a scalar fixture where `s32 tmp;` is used before `s32 count;`, then `count` is assigned and returned. Assert the candidate returns `tmp`.

- [ ] **Step 3: Add rejection tests**

Use parametrized fixtures and assert no `same_type_local_lifetime_reuse` probe for:

```text
earlier local used after later local first use
later local first event is a read rather than a simple assignment
&cur, &prev, & cur, or & prev address taking
later declaration inside an if block
nested declaration shadowing either candidate name
#if region inside the target body
label, case, or default inside the target body
same local names with different normalized types
later declaration with an initializer
candidate declaration line with a trailing comment
name only appearing in comments or string literals
valid candidate with comments/literals containing the later local name; those texts must remain unchanged
valid candidate with member names like state.prev or state->prev; member names must not be counted or rewritten
valid candidate containing braces in comments/literals; depth tracking must still treat only true top-level declarations as top-level
parenthesized address taking such as &((prev))
nested same-name declaration with initializer or trailing comment
loop cross-iteration lifetime hazards
```

- [ ] **Step 4: Add direct mutator test**

Add a direct `apply_mutator` test:

```python
body = (
    "\n"
    "    ItemLink* cur;\n"
    "    ItemLink* prev;\n"
    "    cur = link->next;\n"
    "    use(cur);\n"
    "    prev = it_802BCB88_prev(link);\n"
    "    use(prev);\n"
)
replacement = (
    "\n"
    "    ItemLink* cur;\n"
    "    cur = link->next;\n"
    "    use(cur);\n"
    "    cur = it_802BCB88_prev(link);\n"
    "    use(cur);\n"
)
anchor = Anchor(
    "reuse_same_type_local_lifetime",
    (1, 1 + len(body)),
    {
        "scope_text": body,
        "replacement_scope_text": replacement,
        "reused_name": "cur",
        "original_name": "prev",
        "local_type": "ItemLink*",
    },
)
src = "{" + body + "}\n"
assert apply_mutator("reuse_same_type_local_lifetime", anchor, src) == "{" + replacement + "}\n"
```

Add a stale-span rejection test where `anchor.span` does not exactly cover `scope_text` even though `scope_text` appears elsewhere. Assert `apply_mutator(...) is None`.

- [ ] **Step 5: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

Expected: fails because the new mutator key and anchors do not exist yet.

### Task 2: Implement Scoped Replacement Mutator And Metadata

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [ ] **Step 1: Add mutator**

In `mutators.py`, add:

```python
def _reuse_same_type_local_lifetime(anchor: Anchor, source_text: str) -> Optional[str]:
    scope_text = anchor.payload.get("scope_text", "")
    replacement_scope_text = anchor.payload.get("replacement_scope_text", "")
    if not scope_text or not replacement_scope_text or scope_text == replacement_scope_text:
        return None
    start, end = anchor.span
    if 0 <= start < end <= len(source_text) and source_text[start:end] == scope_text:
        return source_text[:start] + replacement_scope_text + source_text[end:]
    return None
```

Register `"reuse_same_type_local_lifetime": _reuse_same_type_local_lifetime` in `_DISPATCH`.

- [ ] **Step 2: Update family metadata**

In `DEFAULT_TRANSFORM_FAMILIES`, set:

```python
mutator_keys=("reuse_same_type_local_lifetime",)
generated_probe_form="reuse an earlier same-type local after its proven non-overlapping lifetime"
```

Add `"reuse_same_type_local_lifetime"` to `DIRECTED_MUTATOR_KEYS`. Update catalog notes and docs so the family is not record-only. Update the directed mutator count text from 27 to 28 and headline concrete forms from 80 to 81.

- [ ] **Step 3: Run metadata and mutator tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

Expected: mutator and catalog tests pass; probe tests still fail until anchors are generated.

### Task 3: Implement Same-Type Lifetime Reuse Anchors

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Add declaration and line helpers**

Add helpers near the existing full-source anchor helpers:

```python
@dataclass(frozen=True)
class _LocalReuseDecl:
    type_name: str
    name: str
    line: str
    line_span: tuple[int, int]
    remove_span: tuple[int, int]
    name_span: tuple[int, int]
```

Implement `_text_line_records_with_newline`, `_normalize_local_reuse_type`, `_is_supported_local_reuse_type`, `_iter_local_reuse_decls`, `_identifier_mentions`, and `_build_reuse_scope_text`.

- [ ] **Step 2: Implement conservative guards**

The generator must reject the target body if:

```python
"#" in searchable_body
re.search(r"(?m)^[ \t]*(?:case\b.*:|default:|[A-Za-z_]\w*\s*:)", searchable_body)
re.search(r"\bvolatile\b", searchable_body)
```

For each candidate pair, reject if:

```python
decl depths are not zero, computed from comment/literal-blanked text
declaration line contains //, /*, or */
declaration has an initializer
types differ
either name is address-taken via `&\s*name`
either name is address-taken via parenthesized forms such as `&((name))`
either name appears before its declaration
either name has a nested declaration
the replacement region has any same-name declaration line, including initializer or trailing-comment forms
earlier local has no post-declaration use
later local has no post-declaration use
last earlier-local use is not before first later-local use
first later-local use is not a simple assignment LHS
the target body contains `for`, `while`, or `do`
```

Identifier matching must run on `_blank_literals_and_comments(body_inner)` and skip matches preceded by `.` or `->` so field names are not rewritten.

- [ ] **Step 3: Yield anchors**

Build replacement scope text by deleting the later declaration line and replacing every later-local use span after the declaration with the earlier name. Yield:

```python
Anchor(
    mutator_key="reuse_same_type_local_lifetime",
    span=(body_inner_start, body_inner_end),
    payload={
        "scope_text": body_inner,
        "replacement_scope_text": replacement_scope_text,
        "reused_name": earlier.name,
        "original_name": later.name,
        "local_type": earlier.type_name,
        "reused_decl_span": absolute earlier declaration span,
        "original_decl_span": absolute later declaration span,
        "first_original_use": absolute first later use,
        "last_reused_use": absolute last earlier use,
        "replacement_spans": absolute later-use replacement spans,
        "replacement_count": len(replacement_spans),
        "removed_decl_line": later.line,
    },
)
```

Call this generator from `_iter_full_source_anchors`.

- [ ] **Step 4: Run transform-corpus tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/search/directed/test_transform_corpus.py -q
```

Expected: same-type local reuse positive and rejection tests pass.

### Task 4: Verify, Smoke, And Resolve

**Files:**
- No additional source files beyond Tasks 1-3.

- [ ] **Step 1: Run focused test set**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run syntax and diff checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q tools/melee-agent/src/search/directed tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run command smoke**

Create a temporary C fixture with the pointer example and run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search plan-transforms \
  -f target -u melee/test/target \
  --force-phys 1:3 \
  --source-file /tmp/same_type_reuse.c \
  --write-probes /tmp/same-type-probes \
  --json
```

Expected: JSON includes a `same_type_local_lifetime_reuse` probe with `mutator_key` `reuse_same_type_local_lifetime`, and the written same-type candidate contains `cur = it_802BCB88_prev(link);`.

- [ ] **Step 4: Refresh editable install**

Run the repo doctor/fix path or editable install refresh from `/Users/mike/code/melee` so `/opt/homebrew/bin/melee-agent` imports this checkout.

- [ ] **Step 5: Resolve issue and commit**

Resolve only #688:

```bash
melee-agent issue resolve 688 --note "fixed in <commit>: added guarded same-type local lifetime reuse transform-corpus probes"
```

Commit all changed spec, plan, test, production, and doc files on `master`.
