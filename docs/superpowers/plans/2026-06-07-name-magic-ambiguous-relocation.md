# Name-Magic Ambiguous Relocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug mutate name-magic-source-declarations` materialize bounded candidates for ambiguous relocation-pair evidence instead of stopping at zero probes.

**Architecture:** Extend the name-magic source generator to preserve compatible partial relocation evidence when ambiguity is detected, then add a no-edit BSS source-binding probe that can be scored through the existing whole-source candidate path. Keep the CLI scoring and real-tree restore behavior unchanged.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `tools/melee-agent` modules.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/name_magic_source.py`
  - Preserve compatible ambiguous relocation alternatives in parsed evidence.
  - Add safe top-level declaration lookup for named BSS source bindings.
  - Generate `bss-anchor-source-binding` probes.
- Modify `tools/melee-agent/src/cli/debug.py`
  - Allow `bss-anchor-source-binding` as a scoreable name-magic source operator.
  - Allow retained ambiguous relocation evidence through the probe generation gate.
  - Exclude no-edit BSS binding variants from validated source-fix verdicts.
- Modify `tools/melee-agent/tests/test_name_magic_source.py`
  - Cover parser retention and generator BSS binding behavior.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`
  - Cover CLI JSON/scoring behavior for generated BSS binding probes.

## Task 1: Parser and Generator Regression Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_name_magic_source.py`

- [ ] **Step 1: Add parser regression for retained ambiguous alternatives**

Append this test near the existing ambiguous relocation parser test:

```python
def test_parse_name_magic_relocations_retains_ambiguous_compatible_alternatives() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
    assert evidence.reason == "multiple relocation lines at offset 038"
    assert [
        (reloc.offset, reloc.kind, reloc.expected_symbol, reloc.current_symbol)
        for reloc in evidence.relocations
    ] == [
        ("038", "R_PPC_ADDR16_LO", "mnDiagram_804A0750", "...bss.0"),
        ("038", "R_PPC_ADDR16_LO", "mnDiagram_804A076C", "...bss.0"),
    ]
```

- [ ] **Step 2: Add generator regression for ambiguous BSS source binding**

Append this test near the existing BSS anchor tests:

```python
def test_generate_name_magic_source_probes_materializes_ambiguous_bss_binding() -> None:
    source = textwrap.dedent(
        """\
        typedef struct DemoBss {
            u8 values[0x20];
        } DemoBss;

        DemoBss mnDiagram_804A0750;

        void demo_fn(void)
        {
            sink(&mnDiagram_804A0750);
        }
        """
    )
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "demo_fn",
        payload,
        {},
    )

    assert blocker is None
    assert [probe.operator for probe in probes] == ["bss-anchor-source-binding"]
    assert probes[0].source_text == source
    assert probes[0].edits == ()
    assert probes[0].provenance["expected_symbol"] == "mnDiagram_804A0750"
    assert probes[0].provenance["current_symbol"] == "...bss.0"
    assert probes[0].provenance["declaration_start"] == source.index(
        "DemoBss mnDiagram_804A0750;"
    )
```

- [ ] **Step 3: Add generator rejection regression for unsafe BSS sites**

Append this test near the same BSS tests:

```python
def test_bss_anchor_source_binding_rejects_unsafe_declarations() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    function_local = textwrap.dedent(
        """\
        void demo_fn(void)
        {
            DemoBss mnDiagram_804A0750;
            sink(&mnDiagram_804A0750);
        }
        """
    )
    prototype = "void mnDiagram_804A0750(void);\nvoid demo_fn(void) {}\n"
    multi = "DemoBss mnDiagram_804A0750, other;\nvoid demo_fn(void) {}\n"
    macro = "#if 1\nDemoBss mnDiagram_804A0750;\n#endif\nvoid demo_fn(void) {}\n"

    for source in (function_local, prototype, multi, macro):
        assert generate_name_magic_source_probes(source, "demo_fn", payload, {}) == (
            [],
            NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
        )
```

- [ ] **Step 4: Run tests and verify they fail before implementation**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_name_magic_source.py -q -k 'ambiguous_compatible_alternatives or ambiguous_bss_binding or unsafe_declarations'
```

Expected before implementation: failures showing no retained ambiguous relocations and no BSS binding probe.

## Task 2: Parser and Generator Implementation

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/name_magic_source.py`

- [ ] **Step 1: Preserve compatible ambiguous alternatives**

Update `parse_name_magic_relocation_evidence` so it does not return immediately when an offset has multiple expected or current relocation lines. For each offset:

```python
if len(expected) != 1 or len(current) != 1:
    compatible = _compatible_name_magic_relocations(offset, expected, current)
    relocations.extend(compatible)
    ambiguous_reason = f"multiple relocation lines at offset {offset}"
    continue
```

Add helper `_compatible_name_magic_relocations(offset, expected, current)` that returns `NameMagicRelocation` entries only when kinds match, expected symbols are named source symbols, current symbols are supported, and section-anchor offset expressions remain blocked.
The helper must preserve diff order within the offset, dedupe by `(offset, kind, expected_symbol, current_symbol)`, and accept a `limit` so retained ambiguous alternatives are capped before materialization.

- [ ] **Step 2: Return partial evidence with ambiguous blocker**

After the offset loop, return partial ambiguous evidence when compatible alternatives were retained:

```python
if ambiguous_reason is not None and relocations:
    return NameMagicEvidence(
        relocations,
        len(residual_offsets),
        NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR,
        ambiguous_reason,
    )
```

Keep existing blockers for incompatible kind mismatches and unsupported named-symbol cases when no compatible ambiguous alternatives exist. If an ambiguous group has no compatible retained alternatives, return the existing zero-relocation `AMBIGUOUS_RELOCATION_PAIR` blocker.

- [ ] **Step 3: Add safe top-level declaration lookup**

Add `_top_level_named_definition_span(source, symbol)` beside the existing static-definition helpers. It should support non-static top-level definitions like `mnDiagram_804A0750` and reuse the same top-level declaration scan constraints:

- outside preprocessor depth,
- declaration span does not include preprocessor lines,
- no top-level comma,
- no top-level function/prototype parentheses,
- final declared identifier equals `symbol`.
- optional leading `static` is allowed, but not required.

Return the declaration start and end offsets.

- [ ] **Step 4: Add BSS source-binding probe**

Add `_bss_anchor_source_binding_probe(source, relocation, index)` that returns:

```python
NameMagicSourceProbe(
    label=f"bss-anchor-source-binding-{index}",
    operator="bss-anchor-source-binding",
    description=f"bind {relocation.current_symbol} to {relocation.expected_symbol} source declaration",
    source_text=source,
    edits=(),
    provenance={
        **_probe_provenance(relocation),
        "declaration_start": declaration.decl_start,
        "declaration_end": declaration.decl_end,
    },
)
```

If the declaration lookup fails, return `NameMagicBlocker.UNSUPPORTED_SOURCE_SITE`.

- [ ] **Step 5: Let ambiguous partial evidence generate probes**

In `generate_name_magic_source_probes`, only return immediately on blockers other than `AMBIGUOUS_RELOCATION_PAIR`. If the blocker is `AMBIGUOUS_RELOCATION_PAIR` but no relocations were retained, keep returning the blocker. Remove the early all-BSS ceiling return. In the relocation loop, route `...bss.` through `_bss_anchor_source_binding_probe`.

- [ ] **Step 6: Run focused generator tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_name_magic_source.py -q
```

Expected: all tests in the file pass.

## Task 3: CLI Scoring Regression

**Files:**
- Modify: `tools/melee-agent/src/cli/debug.py`
- Modify: `tools/melee-agent/tests/test_debug_cli_reorg.py`

- [ ] **Step 1: Add CLI regression test for ambiguous generation gate**

Append a test near the existing `name-magic-source-declarations` CLI tests:

```python
def test_name_magic_source_declarations_scores_generated_bss_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        "DemoBss mnDiagram_804A0750;\\nvoid fn_80000000(void) { sink(&mnDiagram_804A0750); }\\n",
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
                    "++038: R_PPC_ADDR16_LO\t...bss.0",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {"anonymous_sdata2": {}, "name_magic_suggestions": []},
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            92.70412,
            None,
            False,
            {"match": False, "fuzzy_match_percent": 92.70412},
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["probe_count"] == 1
    assert payload["blocker"] == "no-name-magic-candidate"
    assert payload["stop_condition"]["kind"] == "unvalidated"
    assert payload["probes"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["final_match_percent"] == 92.70412
```

- [ ] **Step 2: Add CLI regression test excluding BSS binding from validated fixes**

Append a second test near the first CLI regression:

```python
def test_name_magic_source_declarations_bss_binding_is_not_validated_fix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        "DemoBss mnDiagram_804A0750;\\nvoid fn_80000000(void) { sink(&mnDiagram_804A0750); }\\n",
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
                    "++038: R_PPC_ADDR16_LO\t...bss.0",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {"anonymous_sdata2": {}, "name_magic_suggestions": []},
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            100.0,
            None,
            True,
            {"match": True, "fuzzy_match_percent": 100.0},
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-name-magic-candidate"
    assert payload["stop_condition"]["kind"] == "unvalidated"
    assert payload["variants"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["no_name_magic_match"] is True
```

- [ ] **Step 3: Run CLI regressions and verify they fail before CLI changes**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py -q -k 'generated_bss_binding or bss_binding_is_not_validated_fix'
```

Expected before implementation: failure due zero probes, unsupported operator, or false validated status.

- [ ] **Step 4: Update CLI generation gate and operator allow-list**

Add `"bss-anchor-source-binding"` to `_NAME_MAGIC_SOURCE_CANDIDATE_OPERATORS` in `tools/melee-agent/src/cli/debug.py`.
Update the probe-generation condition so it calls `generate_name_magic_source_probes` when:

```python
source_text is not None and (
    parsed.blocker is None
    or parsed.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
)
```

- [ ] **Step 5: Exclude no-edit bindings from validated/source-fixable decisions**

In `mutate_name_magic_source_declarations_cmd`, update the `validated` predicate so `bss-anchor-source-binding` cannot validate the command:

```python
variant.get("operator") != "bss-anchor-source-binding"
```

In `_name_magic_section_anchor_verdict`, only consider operators that produce source edits. Do not add `bss-anchor-source-binding` to the fixable operator set.

- [ ] **Step 6: Run affected CLI tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py -q -k 'name_magic_source_declarations'
```

Expected: all selected CLI tests pass.

## Task 4: Verification and Commit

**Files:**
- Commit all modified source, tests, spec, and plan files.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_name_magic_source.py tools/melee-agent/tests/test_debug_cli_reorg.py -q -k 'name_magic_source or ambiguous or bss_binding'
```

Expected: selected tests pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m py_compile tools/melee-agent/src/mwcc_debug/name_magic_source.py tools/melee-agent/src/cli/debug.py tools/melee-agent/tests/test_name_magic_source.py tools/melee-agent/tests/test_debug_cli_reorg.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run live smoke without scoring**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate name-magic-source-declarations -f mnDiagram_80242C0C --source-file src/melee/mn/mndiagram.c --no-compile-probes --json
```

Expected: JSON includes `probe_count` greater than 0 and at least one probe with operator `bss-anchor-source-binding`.

- [ ] **Step 4: Commit**

Stage only feature files:

```bash
git add docs/superpowers/specs/2026-06-07-name-magic-ambiguous-relocation-design.md \
  docs/superpowers/plans/2026-06-07-name-magic-ambiguous-relocation.md \
  tools/melee-agent/src/mwcc_debug/name_magic_source.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_name_magic_source.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "Materialize ambiguous name-magic relocation probes"
```
