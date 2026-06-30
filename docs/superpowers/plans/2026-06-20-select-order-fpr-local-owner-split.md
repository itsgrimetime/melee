# Select-Order FPR Local Owner-Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit focused select-order window source probes for source-attributed FPR locals whose visible float assignments are rejected by the generic statement mover.

**Architecture:** Extend the existing `window_order_source` planner instead of adding a new command. The local attribution branch keeps normal hoist/sink moves first, then falls back to a conservative float owner-split probe with specific terminal blockers when the assignment is visible but unsafe.

**Tech Stack:** Python 3.11, Typer CLI, pytest, tree-sitter-backed statement grouping, existing `LifetimeLayoutProbe` probe payloads.

## Global Constraints

- Do not add a new CLI command; keep `debug select-order-search` as the public surface.
- Preserve the current direct movable-local path when `statement_move.extract_movable_units` finds exactly one legal unit.
- When `source_line` is present, the direct movable-local path must only use a movable write whose line range contains that line; unrelated movable writes for the same local must not mask the owner-split fallback.
- Only split assignable scalar locals whose normalized type is exactly `f32`, `float`, or `double`.
- Reject `const`, `static`, pointer, array, and multi-declarator local owners instead of copying qualifiers into synthetic declarations.
- Accept RHS shapes made from one term or one binary expression using `+`, `-`, or `*`; terms may be identifiers, dotted field reads, numeric literals, float literals, or casts of those terms.
- Reject calls, assignments, comma expressions, increments, ternaries, parenthesized compound expressions, address-taking, array indexing, pointer dereferences, `->`, and unknown non-local reads.
- A visible but unsplittable local assignment must report a specific local-owner terminal blocker, not `no-movable-local-write`.
- Update the select-order JSON diagnostic note so it no longer claims product expressions are only covered by transform-corpus probes.
- Preserve unrelated dirty files in `/Users/mike/code/melee`; stage only files changed for issue #869.

---

### Task 1: Local FPR Owner-Split Planner

**Files:**
- Modify: `tools/melee-agent/src/search/directed/window_order_source.py`
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Create: no production files

**Interfaces:**
- Consumes: existing `plan_window_order_source_probes(source_text, function=..., fallback_leads=..., source_attributions=..., max_probes=...)`.
- Produces: existing `LifetimeLayoutProbe` objects with `operator == "window-order-source-steering"` and provenance `synthetic_source_probe.handler == "local-fpr-owner-split"`.

- [ ] **Step 1: Write the casted FPR local regression test**

Add this test near the existing FPR window-order source probe tests in `tools/melee-agent/tests/test_select_order_search.py`:

```python
def test_select_order_search_materializes_fpr_local_product_owner_split(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "fpr-baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(FPR_BASELINE)
    source.write_text(textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 y_spacing_alias_32_0;
            f32 col_offset;

            y_spacing_alias_32_0 = y_spacing;
            col_offset = y_spacing_alias_32_0 * (f32) col;
            sink(col_offset);
        }
    """))

    fallback = {
        "ran": True,
        "reason": "window-order fallback leads found",
        "leads": [{
            "target_ig": 32,
            "order_move": ["before", 37],
            "move_distance": 5,
            "perturbed_reg": 28,
        }],
    }
    attrs = {
        32: {
            "kind": "local",
            "name": "col_offset",
            "type": "f32",
            "source_file": str(source),
            "source_line": 10,
            "expression": "col_offset = y_spacing_alias_32_0 * (f32) col",
            "confidence": "pcode-first-def",
        },
    }

    monkeypatch.setattr(
        debug_cli,
        "_register_tiebreak_window_order_fallback",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_attributions_for_leads",
        lambda **kwargs: attrs,
    )
    monkeypatch.setattr(
        debug_cli,
        "_append_transform_corpus_probes",
        lambda probes, **kwargs: probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "f32<f37",
            "--class",
            "1",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--force-phys",
            "32:28",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    diagnostics = payload["window_order_probe_diagnostics"]
    lead = next(item for item in diagnostics["lead_diagnostics"] if item["target_ig"] == 32)
    assert lead["status"] == "materialized"
    assert lead["synthetic_source_probe"]["handler"] == "local-fpr-owner-split"
    assert lead["source_local"] == "col_offset"
    assert "terminal_blocker" not in lead
    assert "source_diff" in lead
    assert diagnostics["listed_source_probes"] == 1
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "window-order-source-steering"
    )
    assert probe["provenance"]["synthetic_source_probe"]["handler"] == "local-fpr-owner-split"
    assert "window_order_synthetic_col_offset" in lead["source_diff"]
    assert "col_offset = window_order_synthetic_col_offset" in lead["source_diff"]
    try_action = next(
        action for action in payload["source_bridge_summary"]["ranked_actions"]
        if action["kind"] == "try-window-order-source-move"
    )
    assert try_action["synthetic_source_probe"]["handler"] == "local-fpr-owner-split"
    assert "window_order_synthetic_col_offset" in try_action["source_diff"]
```

- [ ] **Step 2: Write the specific blocker regression test**

Add this focused planner-level test in the same file:

```python
def test_window_order_source_probe_reports_specific_blocker_for_unsplittable_fpr_local() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        f32 make_value(void);
        void sink(f32 value);

        void fn_80000000(void)
        {
            f32 col_offset;

            col_offset = make_value();
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={32: {"kind": "local", "name": "col_offset", "source_line": 9}},
        max_probes=4,
    )

    assert plan.probes == []
    diag = plan.lead_diagnostics[0]
    assert diag["terminal_blocker"] == "local-source-owner-unsupported-rhs"
    assert diag["source_local"] == "col_offset"
```

- [ ] **Step 3: Write declaration and uniqueness blocker tests**

Add these planner-level tests in the same file:

```python
def test_window_order_source_probe_reports_nonfloat_blocker_for_static_fpr_local() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing)
        {
            static f32 col_offset;

            col_offset = y_spacing * y_spacing;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={32: {"kind": "local", "name": "col_offset", "source_line": 8}},
        max_probes=4,
    )

    assert plan.probes == []
    assert plan.lead_diagnostics[0]["terminal_blocker"] == "local-source-owner-nonfloat"


def test_window_order_source_probe_source_line_disambiguates_local_owner() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 col_offset;

            col_offset = y_spacing;
            col_offset = y_spacing * (f32) col;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={32: {"kind": "local", "name": "col_offset", "source_line": 9}},
        max_probes=4,
    )

    assert len(plan.probes) == 1
    assert plan.lead_diagnostics[0]["status"] == "materialized"

    stale = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 32, "order_move": ["before", 37]}],
        source_attributions={32: {"kind": "local", "name": "col_offset", "source_line": 99}},
        max_probes=4,
    )

    assert stale.probes == []
    assert stale.lead_diagnostics[0]["terminal_blocker"] == "local-source-owner-no-unique-assignment"
```

- [ ] **Step 4: Write the FPR-temp casted multiply regression test**

Add this planner-level test in the same file:

```python
def test_window_order_source_probe_fpr_temp_owner_accepts_casted_multiply() -> None:
    from src.search.directed.window_order_source import plan_window_order_source_probes

    source = textwrap.dedent("""\
        typedef float f32;
        void sink(f32 value);

        void fn_80000000(f32 y_spacing, int col)
        {
            f32 col_offset;

            col_offset = y_spacing * (f32) col;
            sink(col_offset);
        }
    """)

    plan = plan_window_order_source_probes(
        source,
        function="fn_80000000",
        fallback_leads=[{"target_ig": 46, "order_move": ["before", 32], "source": "force-phys-attributed-temp"}],
        source_attributions={
            46: {"kind": "fpr-temp", "expression": "fmuls f46,f45,f44"},
        },
        max_probes=4,
    )

    assert len(plan.probes) == 1
    diag = plan.lead_diagnostics[0]
    assert diag["status"] == "materialized"
    assert diag["synthetic_source_probe"]["handler"] == "fpr-arith-owner-split"
    assert diag["synthetic_source_probe"]["split_expression"] == "y_spacing * (f32) col"
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_materializes_fpr_local_product_owner_split \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_reports_specific_blocker_for_unsplittable_fpr_local \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_reports_nonfloat_blocker_for_static_fpr_local \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_source_line_disambiguates_local_owner \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_fpr_temp_owner_accepts_casted_multiply \
  -q
```

Expected: tests fail before the production change because the local product assignment is reported as `no-movable-local-write` or no specific local-owner blocker exists.

- [ ] **Step 6: Add local FPR owner-split helpers**

In `tools/melee-agent/src/search/directed/window_order_source.py`, add helpers near `_matching_assignment_owners`:

```python
_FLOAT_EXPR_TERM_RE = re.compile(
    rf"(?:{_CASTED_SIMPLE_TERM_RE.pattern}|{_SIMPLE_TERM_RE.pattern})"
)
_LOCAL_FLOAT_BINARY_EXPR_RE = re.compile(
    rf"\s*{_FLOAT_EXPR_TERM_RE.pattern}\s*(?:[+\-*])\s*"
    rf"{_FLOAT_EXPR_TERM_RE.pattern}\s*"
)
_LOCAL_FLOAT_FORBIDDEN_RHS_RE = re.compile(r"\+\+|--|->|\[|\]|&|\?|,|\b[A-Za-z_]\w*\s*\(")


def _local_fpr_decl_type(
    group: statement_move.SiblingGroup,
    local_name: str,
) -> tuple[str, statement_move.SiblingStmt] | None:
    decl = _decl_type_for_local(group.siblings, local_name)
    if decl is None:
        return None
    type_text, sibling = decl
    tokens = set(type_text.replace("*", " ").split())
    if "*" in type_text or tokens & {"const", "static", "volatile"}:
        return None
    if _normalized_decl_type(type_text) not in _FLOAT_DECL_TYPES:
        return None
    return type_text, sibling


def _local_float_rhs_reads(rhs: str) -> set[str]:
    without_cast_types = re.sub(
        r"\(\s*[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\)",
        " ",
        rhs,
    )
    without_fields = re.sub(r"\.\s*[A-Za-z_]\w*", "", without_cast_types)
    without_numbers = re.sub(r"\b\d[\w.]*", "", without_fields)
    return {
        token for token in re.findall(r"[A-Za-z_]\w*", without_numbers)
        if token not in {"f", "F"}
    }


def _float_local_split_expression(rhs: str, locals_: set[str]) -> str | None:
    stripped = rhs.strip()
    if "=" in stripped or _LOCAL_FLOAT_FORBIDDEN_RHS_RE.search(stripped):
        return None
    if not _local_float_rhs_reads(stripped) <= locals_:
        return None
    if (
        _FLOAT_EXPR_TERM_RE.fullmatch(stripped) is not None
        or _LOCAL_FLOAT_BINARY_EXPR_RE.fullmatch(stripped) is not None
    ):
        return stripped
    return None


def _visible_local_assignment_owners(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
    *,
    source_line: object = None,
) -> list[_OwnerAssignment]:
    matches: list[_OwnerAssignment] = []
    for group in groups:
        if local_name not in group.locals_:
            continue
        for sibling in group.siblings:
            if sibling.kind != "simple":
                continue
            match = _SIMPLE_ASSIGN_RE.match(sibling.text)
            if match is None or match.group("lhs") != local_name:
                continue
            if isinstance(source_line, int):
                start, end = sibling.line_range
                if not start <= source_line <= end:
                    continue
            matches.append(
                _OwnerAssignment(
                    group=group,
                    sibling=sibling,
                    local_name=local_name,
                    rhs=match.group("rhs").strip(),
                    indent=match.group("indent"),
                )
            )
    return matches


def _local_fpr_owner_split(
    groups: list[statement_move.SiblingGroup],
    local_name: str,
    source_attr: Any,
) -> _SyntheticOwnerResult:
    source_line = _attr_value(source_attr, "source_line")
    owners = _visible_local_assignment_owners(
        groups,
        local_name,
        source_line=source_line,
    )
    if not owners and isinstance(source_line, int):
        owners = _visible_local_assignment_owners(groups, local_name)
    if len(owners) != 1:
        return _SyntheticOwnerResult(
            (),
            {"handler": "local-fpr-owner-split", "owner_local": local_name},
            "local-source-owner-no-unique-assignment",
        )
    owner = owners[0]
    decl = _local_fpr_decl_type(owner.group, owner.local_name)
    if decl is None:
        return _SyntheticOwnerResult(
            (),
            {"handler": "local-fpr-owner-split", "owner_local": local_name},
            "local-source-owner-nonfloat",
        )
    split_expression = _float_local_split_expression(
        owner.rhs,
        set(owner.group.locals_),
    )
    if split_expression is None:
        return _SyntheticOwnerResult(
            (),
            {
                "handler": "local-fpr-owner-split",
                "owner_local": local_name,
                "rhs": owner.rhs,
            },
            "local-source-owner-unsupported-rhs",
        )
    metadata = {
        "handler": "local-fpr-owner-split",
        "owner_local": owner.local_name,
        "split_expression": split_expression,
    }
    return _SyntheticOwnerResult(
        (
            _SyntheticOwnerCandidate(
                _OwnerAssignment(
                    group=owner.group,
                    sibling=owner.sibling,
                    local_name=owner.local_name,
                    rhs=owner.rhs,
                    indent=owner.indent,
                    split_expression=split_expression,
                ),
                metadata,
            ),
        ),
        metadata,
        None,
    )
```

- [ ] **Step 7: Wire the helper into the local attribution branch**

In `plan_window_order_source_probes`, filter the normal local movable matches before the existing count checks:

```python
        source_line = _attr_value(source_attr, "source_line")
        if isinstance(source_line, int):
            line_matches = [
                match for match in matches
                if (
                    match[2].index_range
                    and match[1][match[2].index_range[0]].line_range[0]
                    <= source_line
                    <= match[1][match[2].index_range[1]].line_range[1]
                )
            ]
            matches = line_matches
```

Then replace the `len(matches) == 0` branch for normal locals with:

```python
        if len(matches) == 0:
            synthetic = _local_fpr_owner_split(groups, local_name, source_attr)
            materialize_synthetic_result(
                diag=diag,
                lead=lead,
                target_ig=target_ig,
                direction=direction,
                source_attr=source_attr,
                synthetic=synthetic,
                default_blocker="local-source-owner-unsupported-rhs",
            )
            lead_diagnostics.append(diag)
            continue
```

Also make `_fpr_split_expressions` use `_FLOAT_EXPR_TERM_RE` for multiply and subtract so casted terms work on the existing `fpr-temp` path:

```python
    term = _FLOAT_EXPR_TERM_RE.pattern
```

- [ ] **Step 8: Update the select-order diagnostic note**

In `tools/melee-agent/src/cli/debug/__init__.py`, update the `window_order_probe_diagnostics["note"]` text to mention that assignable float local product owners can materialize owner-split probes. Keep the wording compact and do not change any command-line options.

- [ ] **Step 9: Run the focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_materializes_fpr_local_product_owner_split \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_reports_specific_blocker_for_unsplittable_fpr_local \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_reports_nonfloat_blocker_for_static_fpr_local \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_source_line_disambiguates_local_owner \
  tools/melee-agent/tests/test_select_order_search.py::test_window_order_source_probe_fpr_temp_owner_accepts_casted_multiply \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_promotes_attributed_force_phys_fpr_temp_to_lead \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 10: Run the narrow CLI smoke**

Run:

```bash
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
```

Expected: exit code 0 and help text is written.

- [ ] **Step 11: Commit the issue #869 files**

Stage only files for this issue:

```bash
git add \
  docs/superpowers/specs/2026-06-20-select-order-fpr-local-owner-split-design.md \
  docs/superpowers/plans/2026-06-20-select-order-fpr-local-owner-split.md \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/search/directed/window_order_source.py \
  tools/melee-agent/tests/test_select_order_search.py
git commit -m "Materialize FPR local owner-split source probes"
```
