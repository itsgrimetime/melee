# Synthetic Owner-Split Realization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make synthetic owner-split node-set deltas produce realizable source candidates and let compatible overlapping introduction hunks recombine.

**Architecture:** Patch the existing node-set-split binding path to convert tree-sitter byte ranges before editing strings, then extend `debug search combine` with a narrow compatible-overlap merge. The command surfaces stay unchanged.

**Tech Stack:** Python, Typer CLI, pytest, existing `tools/melee-agent` test helpers.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/node_set_split.py` for byte-safe binding-site discovery and rewriting.
- Modify `tools/melee-agent/src/search/cli/__init__.py` for compatible overlapping introduction hunk merging.
- Modify `tools/melee-agent/tests/test_node_set_split.py` for node-set regression coverage.
- Modify `tools/melee-agent/tests/search/test_cli_smoke.py` for combine command regression coverage.

## Task 1: Byte-Safe Synthetic Owner-Split Binding

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [x] **Step 1: Write failing non-ASCII owner-split tests**

Add tests to `tools/melee-agent/tests/test_node_set_split.py`:

```python
def test_generate_node_set_introduce_binding_handles_non_ascii_prefix_owner_split() -> None:
    source = (
        "/// value \\u2192 rendered name\\n"
        "/// non-ascii prefix shifts UTF-8 byte offsets\\n"
        "typedef unsigned char u8;\\n"
        "void fn_test(void) {\\n"
        "    u8* dst;\\n"
        "    u8* dst_iter;\\n"
        "    dst_iter = dst;\\n"
        "    use(dst_iter);\\n"
        "}\\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 44,
            "current_register": "r24",
            "desired_registers": ["r25"],
            "source": {
                "kind": "synthetic-owner-split",
                "expression": "dst",
                "type": "u8*",
                "introduce_binding": True,
            },
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    candidate_text = "\\n".join(patch.patched_source for patch in patches)
    assert "u8* dst_bind_44_0;" in candidate_text
    assert "dst_bind_44_0 = dst;" in candidate_text
    assert "dst_iter = dst_bind_44_0;" in candidate_text


def test_generate_coupled_composes_non_ascii_local_and_owner_split() -> None:
    source = (
        "/// non-ascii prefix: \\u2192 grid\\n"
        "typedef unsigned char u8;\\n"
        "void fn_test(void) {\\n"
        "    u8* dst;\\n"
        "    u8* dst_iter;\\n"
        "    int holder;\\n"
        "    dst_iter = dst;\\n"
        "    holder = make();\\n"
        "    use(dst_iter, holder);\\n"
        "}\\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"kind": "local", "name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r25",
                "desired_registers": ["r26"],
                "source": {
                    "kind": "synthetic-owner-split",
                    "expression": "dst",
                    "type": "u8*",
                    "introduce_binding": True,
                },
            },
        ],
    }
    reqs = requests_from_node_set_delta(
        delta, source_text=source, include_introducible=True, max_requests=0
    )

    patches = generate_coupled_node_set_split_patches(
        source, "fn_test", reqs, max_read_sites=1, max_candidates=4
    )

    assert patches
    assert any("dst_bind_44_0" in patch.patched_source for patch in patches)
    assert any("holder_split_34_0" in patch.patched_source for patch in patches)
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_introduce_binding_handles_non_ascii_prefix_owner_split tools/melee-agent/tests/test_node_set_split.py::test_generate_coupled_composes_non_ascii_local_and_owner_split -q
```

Expected: both tests fail because no introduce-binding patch is generated for `dst`.

- [x] **Step 3: Implement byte-to-character conversion in node-set-split**

In `tools/melee-agent/src/mwcc_debug/node_set_split.py`, import the existing helper:

```python
from .source_patch import (
    _byte_range_to_char_range,
    _strip_c_comments,
    build_decl_order_candidates_for_scope,
    explain_decl_reorder_skip,
    find_function,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
)
```

Update `_introduce_binding_sites`, `_statement_span_starts_on_plain_line`,
`_build_introduce_binding_source`, and `_block_top_insert_pos` so every
`StatementSpan.byte_range` or `scope_byte_range` used to slice/edit `source`
is converted with `_byte_range_to_char_range(source, byte_range)` first.

- [x] **Step 4: Run focused node-set tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_introduce_binding_handles_non_ascii_prefix_owner_split tools/melee-agent/tests/test_node_set_split.py::test_generate_coupled_composes_non_ascii_local_and_owner_split tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_introduce_binding_patches_splits_field_expression tools/melee-agent/tests/test_node_set_split.py::test_generate_coupled_composes_bindable_and_introduced_binding -q
```

Expected: all selected tests pass.

## Task 2: Compatible Overlap Recombine

**Files:**
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [x] **Step 1: Write failing combine tests**

Add tests to `tools/melee-agent/tests/search/test_cli_smoke.py`:

```python
def test_search_combine_merges_overlapping_local_introductions(tmp_path: Path) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void fn_test(void) {\\n"
        "    int out;\\n"
        "    out = left + right;\\n"
        "    use(out);\\n"
        "}\\n"
    )
    left = tmp_path / "left.c"
    left.write_text(
        "void fn_test(void) {\\n"
        "    int left_bind_38_0;\\n"
        "    int out;\\n"
        "    left_bind_38_0 = left;\\n"
        "    out = left_bind_38_0 + right;\\n"
        "    use(out);\\n"
        "}\\n"
    )
    right = tmp_path / "right.c"
    right.write_text(
        "void fn_test(void) {\\n"
        "    int right_bind_46_0;\\n"
        "    int out;\\n"
        "    right_bind_46_0 = right;\\n"
        "    out = left + right_bind_46_0;\\n"
        "    use(out);\\n"
        "}\\n"
    )
    score_script = tmp_path / "score_candidate.py"
    score_script.write_text(
        "import json, pathlib, sys\\n"
        "text = pathlib.Path(sys.argv[1]).read_text()\\n"
        "print(json.dumps({\\n"
        "  'byte_score': 7,\\n"
        "  'has_left': 'left_bind_38_0 = left;' in text,\\n"
        "  'has_right': 'right_bind_46_0 = right;' in text,\\n"
        "  'has_composed_assignment': 'out = left_bind_38_0 + right_bind_46_0;' in text,\\n"
        "}))\\n"
    )
    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left}",
            "--candidate", f"right={right}",
            "--out-dir", str(tmp_path / "combined"),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "ok"
    assert combo["merge_strategy"] == "compatible-overlap"
    combined = Path(combo["path"]).read_text()
    assert "int left_bind_38_0;" in combined
    assert "int right_bind_46_0;" in combined
    assert "left_bind_38_0 = left;" in combined
    assert "right_bind_46_0 = right;" in combined
    assert "out = left_bind_38_0 + right_bind_46_0;" in combined
    assert combo["score_result"]["parsed_json"] == {
        "byte_score": 7,
        "has_left": True,
        "has_right": True,
        "has_composed_assignment": True,
    }


def test_search_combine_still_skips_incompatible_overlaps(tmp_path: Path) -> None:
    base = tmp_path / "base.c"
    base.write_text("void fn_test(void) {\\n    out = left + right;\\n}\\n")
    left = tmp_path / "left.c"
    left.write_text("void fn_test(void) {\\n    out = left - right;\\n}\\n")
    right = tmp_path / "right.c"
    right.write_text("void fn_test(void) {\\n    out = left * right;\\n}\\n")

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left}",
            "--candidate", f"right={right}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_merges_overlapping_local_introductions tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_still_skips_incompatible_overlaps -q
```

Expected: the compatible-overlap test fails with `status == "skipped"`; the incompatible-overlap test passes or continues to show the existing skip behavior.

- [x] **Step 3: Implement compatible-overlap merge**

In `tools/melee-agent/src/search/cli/__init__.py`, add helper functions used by
`_merge_source_hunks`:

```python
def _line_is_local_intro(line: str) -> bool:
    text = line.strip()
    return (
        re.match(r"^(?:const\s+)?[A-Za-z_][A-Za-z_0-9]*(?:\s*\*+|\s+)+[A-Za-z_][A-Za-z_0-9]*(?:\s*=\s*[^;]+)?;\s*$", text) is not None
        or re.match(r"^[A-Za-z_][A-Za-z_0-9]*\s*=\s*[^;]+;\s*$", text) is not None
    )


def _simple_assignment_parts(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>[^;]+);\s*$", line)
    if match is None:
        return None
    return match.group("lhs"), match.group("rhs").strip()


def _identifier_substitutions(base_line: str, candidate_line: str) -> dict[str, str] | None:
    base_parts = _simple_assignment_parts(base_line)
    candidate_parts = _simple_assignment_parts(candidate_line)
    if base_parts is None or candidate_parts is None or base_parts[0] != candidate_parts[0]:
        return None
    base_tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[^A-Za-z_]+", base_parts[1])
    candidate_tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[^A-Za-z_]+", candidate_parts[1])
    if len(base_tokens) != len(candidate_tokens):
        return None
    substitutions: dict[str, str] = {}
    for base_token, candidate_token in zip(base_tokens, candidate_tokens):
        if base_token == candidate_token:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", base_token):
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", candidate_token):
            return None
        previous = substitutions.get(base_token)
        if previous is not None and previous != candidate_token:
            return None
        substitutions[base_token] = candidate_token
    return substitutions


def _apply_identifier_substitutions(line: str, substitutions: dict[str, str]) -> str:
    result = line
    for old, new in sorted(substitutions.items(), key=lambda item: -len(item[0])):
        result = re.sub(rf"\b{re.escape(old)}\b", new, result)
    return result


def _merge_compatible_overlapping_hunks(
    base_lines: list[str],
    hunks: list[dict],
) -> tuple[str | None, list[dict]]:
    ordered = sorted(hunks, key=lambda hunk: (int(hunk["base_start"]), int(hunk["base_end"])))
    merged_hunks: list[dict] = []
    cursor = 0
    while cursor < len(ordered):
        group = [ordered[cursor]]
        cursor += 1
        while cursor < len(ordered) and _hunks_overlap(group[-1], ordered[cursor]):
            group.append(ordered[cursor])
            cursor += 1
        if len(group) == 1:
            merged_hunks.append(group[0])
            continue
        starts = {int(hunk["base_start"]) for hunk in group}
        ends = {int(hunk["base_end"]) for hunk in group}
        if len(starts) != 1 or len(ends) != 1:
            return None, []
        start = starts.pop()
        end = ends.pop()
        removed = base_lines[start:end]
        if start == end:
            added: list[str] = []
            for hunk in group:
                if hunk.get("removed"):
                    return None, []
                for line in hunk.get("added") or []:
                    if not _line_is_local_intro(line) or _simple_assignment_parts(line) is not None:
                        return None, []
                    if line not in added:
                        added.append(line)
            merged_hunks.append({**group[0], "kind": "compatible-overlap", "added": added})
            continue
        if any(list(hunk.get("removed") or []) != removed for hunk in group):
            return None, []
        declarations: list[str] = []
        binding_assignments: list[str] = []
        statement_substitutions: dict[str, str] = {}
        base_assignment = next((line for line in removed if _simple_assignment_parts(line) is not None), None)
        if base_assignment is None:
            return None, []
        for hunk in group:
            final_assignment = None
            for line in hunk.get("added") or []:
                if not _line_is_local_intro(line):
                    return None, []
                if _simple_assignment_parts(line) is not None and _simple_assignment_parts(line)[0] == _simple_assignment_parts(base_assignment)[0]:
                    final_assignment = line
                elif re.search(r"\s=\s", line):
                    if line not in binding_assignments:
                        binding_assignments.append(line)
                elif line not in declarations:
                    declarations.append(line)
            if final_assignment is None:
                return None, []
            substitutions = _identifier_substitutions(base_assignment, final_assignment)
            if substitutions is None:
                return None, []
            for old, new in substitutions.items():
                previous = statement_substitutions.get(old)
                if previous is not None and previous != new:
                    return None, []
                statement_substitutions[old] = new
        added = [
            *declarations,
            *binding_assignments,
            _apply_identifier_substitutions(base_assignment, statement_substitutions),
        ]
        merged_hunks.append({**group[0], "kind": "compatible-overlap", "added": added})
    return "compatible-overlap", merged_hunks
```

The helper should only merge overlapping hunks that all share the same
`base_start`/`base_end`, have the same removed base lines, and add C local
declaration or simple assignment lines. Empty-base declaration insertion groups
are merged by unioning unique declarations. Non-empty replacement groups should
infer identifier substitutions from each candidate's rewritten base assignment,
compose those substitutions onto the original base assignment, and return
`("compatible-overlap", merged_hunks)` when successful. Otherwise it returns
`(None, [])`.

Update `_merge_source_hunks` to return both merged text and merge strategy, and
update `_combine_candidate_pair` to include `"merge_strategy"` for successful
combinations.

- [x] **Step 4: Run focused combine tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_merges_overlapping_local_introductions tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_still_skips_incompatible_overlaps tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_recombines_complementary_candidate_deltas tools/melee-agent/tests/search/test_cli_smoke.py::test_search_combine_manual_ranges_recombine_broad_generated_candidates -q
```

Expected: all selected tests pass.

## Task 3: Verification and CLI Smoke

**Files:**
- No new files.

- [x] **Step 1: Run narrow regression suite**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py tools/melee-agent/tests/search/test_cli_smoke.py -q
```

Expected: both focused test modules pass.

- [x] **Step 2: Run command-level smoke checks**

Run:

```bash
if [ -f /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_sort_846_node_set_delta.json ]; then
  melee-agent debug solve node-set-split --node-set-delta /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_sort_846_node_set_delta.json --source-file /Users/mike/.codex/worktrees/eeff/melee/src/melee/mn/mndiagram.c --max-candidates 1 --budget 45 --json
fi
```

Expected: the command no longer returns `blocked_reason: no introduce-binding candidates generated`; it either scores generated candidates, exhausts the bounded candidate, or reports a compiler/scoring diagnostic.

- [x] **Step 3: Commit**

Run:

```bash
git add docs/superpowers/specs/2026-06-19-synthetic-owner-split-realization-design.md docs/superpowers/plans/2026-06-19-synthetic-owner-split-realization.md tools/melee-agent/src/mwcc_debug/node_set_split.py tools/melee-agent/src/search/cli/__init__.py tools/melee-agent/tests/test_node_set_split.py tools/melee-agent/tests/search/test_cli_smoke.py
git commit -m "fix(melee-agent): realize synthetic owner splits"
```
