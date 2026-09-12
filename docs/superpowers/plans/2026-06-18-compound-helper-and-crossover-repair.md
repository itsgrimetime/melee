# Compound Helper And Crossover Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #809, #810, and #811 by adding condition-safe repeated-helper boolean reuse and retained-source crossover repair with frame/FPR frontier reporting.

**Architecture:** Extend existing probe generators and select-order guard repair instead of adding a new command. `pressure_explorer` owns source-lifetime helper rewrites. `debug select-order-search` owns retained seed loading, source-hunk crossover generation, scoring, ledger output, and guard/FPR summaries.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `LifetimeLayoutProbe`, `pressure_signature_from_pcdump`, `score_select_order_candidate`, and select-order guard-repair helpers.

---

### Task 1: Compound Boolean Helper Reuse

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`
- Test: `tools/melee-agent/tests/test_pressure_explorer.py`

- [ ] **Step 1: Write failing condition-reuse tests**

Add tests near the existing `unsupported-call-site-shape` repeated-helper tests:

```python
def test_source_lifetime_repeated_helper_result_reuse_supports_condition_bool_temp() -> None:
    source = textwrap.dedent("""\
        char* GetNameText(int slot);

        s32 fn_80000000(int slot)
        {
            if (GetNameText(slot) != NULL) {
                sink(slot);
            }
            if (GetNameText(slot) != NULL) {
                sink(slot + 1);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
        and probe.provenance.get("reuse_kind") == "condition-bool"
    )
    assert "int ll_probe_helper_exists_0 = GetNameText(slot) != 0;" in probe.source_text
    assert "if (ll_probe_helper_exists_0) {" in probe.source_text
    assert probe.source_text.count("GetNameText(slot)") == 1
    assert probe.provenance["callee"] == "GetNameText"
    assert probe.provenance["occurrences"] == 2
    assert not [
        row for row in summaries
        if row["operator"] == "repeated-helper-result-reuse"
        and row.get("blocker") == "unsupported-call-site-shape"
    ]


def test_source_lifetime_repeated_helper_result_reuse_rewrites_null_equality_to_negated_exists() -> None:
    source = textwrap.dedent("""\
        char* GetNameText(int slot);

        s32 fn_80000000(int slot)
        {
            if (GetNameText(slot) == NULL) {
                sink(slot);
            }
            if (GetNameText(slot) == NULL) {
                sink(slot + 1);
            }
            return 0;
        }
    """)

    probes, _summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(
        probe for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
        and probe.provenance.get("reuse_kind") == "condition-bool"
    )
    assert "if (!ll_probe_helper_exists_0) {" in probe.source_text
    assert "ll_probe_helper_exists_0 == NULL" not in probe.source_text


def test_source_lifetime_repeated_helper_result_reuse_rejects_guarded_short_circuit_arg() -> None:
    source = textwrap.dedent("""\
        char* GetNameText(int slot);

        s32 fn_80000000(int* slot)
        {
            if (slot != NULL && GetNameText(*slot) != NULL) {
                sink(slot);
            }
            if (slot != NULL && GetNameText(*slot) != NULL) {
                sink(slot);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert not [
        probe for probe in probes
        if probe.operator == "repeated-helper-result-reuse"
        and probe.provenance.get("reuse_kind") == "condition-bool"
    ]
    blocked = [
        row for row in summaries
        if row["operator"] == "repeated-helper-result-reuse"
    ]
    assert blocked
    assert blocked[0]["blocker"] == "unsupported-call-site-shape"
```

- [ ] **Step 2: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_pressure_explorer.py::test_source_lifetime_repeated_helper_result_reuse_supports_condition_bool_temp \
  tools/melee-agent/tests/test_pressure_explorer.py::test_source_lifetime_repeated_helper_result_reuse_rewrites_null_equality_to_negated_exists \
  tools/melee-agent/tests/test_pressure_explorer.py::test_source_lifetime_repeated_helper_result_reuse_rejects_guarded_short_circuit_arg
```

Expected: the first two tests fail because no condition-bool probe exists; the guarded short-circuit test should pass or fail with the same unsupported-shape behavior.

- [ ] **Step 3: Implement condition-specific reuse**

In `pressure_explorer`, add helper functions next to `_repeated_helper_occurrence_blocker`:

```python
def _repeated_helper_condition_bool_probe(
    source_text: str,
    function: str,
    occurrences: list[_SimpleHelperCall],
    *,
    temp_name: str,
) -> LifetimeLayoutProbe | None:
    # Validate all occurrences are supported if-condition operands.
    # Compute whole-condition replacements: call != NULL -> temp,
    # call == NULL -> !temp, bare call -> temp.
    # Insert `int {temp_name} = {call} != 0;` at the first condition line.
    ...
```

Use existing utilities: `_line_start`, `_line_end`, `_find_matching_paren`,
`_cast_prefixed_call_range`, `_replace_absolute_slices`,
`_region_has_preprocessor_directive`, `_helper_arg_mutation_blocker`, and
`_next_unique_repeated_helper_temp_name`. The implementation must return
`None` for loops, returns, assignments, labels, case labels, guarded
short-circuit arguments, or any condition not on an `if (...) {` line.

Call this helper from `_probe_repeated_helper_result_reuse` when
`_repeated_helper_occurrence_blocker` returns `unsupported-call-site-shape`.
Return the generated probe with the existing operator
`repeated-helper-result-reuse` and provenance `reuse_kind=condition-bool`.

- [ ] **Step 4: Run focused tests**

Run the red-test command again. Expected: all three tests pass.

### Task 2: Retained Source-Hunk Crossover Probes

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing crossover generator test**

Add a test near `test_select_order_subtractive_source_hunk_repair_generates_reverts_and_type_variants`:

```python
def test_select_order_source_hunk_crossover_generates_donor_recipient_probe() -> None:
    base_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            use(a);
            use(b);
        }
    """)
    left_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            int left_hit = a;
            use(left_hit);
            use(b);
        }
    """)
    right_source = textwrap.dedent("""\
        void fn_80000000(void)
        {
            use(a);
            int right_hit = b;
            use(right_hit);
        }
    """)

    probes = debug_cli._select_order_source_hunk_crossover_probes(
        base_source=base_source,
        seed_sources=[
            {"label": "left", "source_text": left_source, "protected_hits": {"34": 27}},
            {"label": "right", "source_text": right_source, "protected_hits": {"44": 25}},
        ],
        function="fn_80000000",
        max_probes=8,
    )

    probe = next(probe for probe in probes if probe.operator == "source-hunk-crossover")
    assert "int left_hit = a;" in probe.source_text
    assert "int right_hit = b;" in probe.source_text
    assert probe.provenance["repair_action"] == "crossover"
    assert probe.provenance["protected_force_phys_hits"] == {"34": 27, "44": 25}
```

- [ ] **Step 2: Write failing guard-repair scoring test**

Add a CLI-level test like the existing subtractive scoring test. Use two
synthetic candidate source files, monkeypatch compile/scoring so the crossover
source scores as guard accepted with two force-phys hits, and assert the ledger
contains `source-hunk-crossover`.

- [ ] **Step 3: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_hunk_crossover_generates_donor_recipient_probe \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_scores_crossover_source_hunk_probe
```

Expected: failures because `_select_order_source_hunk_crossover_probes` does not exist and guard repair emits no crossover entries.

- [ ] **Step 4: Implement bounded crossover generation**

In `debug/__init__.py`, add `_select_order_source_hunk_crossover_probes` next to
the subtractive source-hunk helper. The helper accepts base source, seed source
records, function name, and max probe count. It extracts function bodies with
`extract_function`, computes executable replacement hunks with
`difflib.SequenceMatcher`, skips non-executable hunks with
`_select_order_source_hunk_has_statement`, applies donor hunks to recipient
function lines, replaces the function body inside the full recipient source,
dedupes by body hash, and emits `LifetimeLayoutProbe` rows with
`operator="source-hunk-crossover"`.

Protect the union of achieved seed hits:

```python
protected = {}
for seed in seed_sources:
    protected.update(seed.get("protected_hits") or {})
```

Cap the generator to `max_probes`, prefer one-hunk donor/recipient crossovers,
then pair-hunk crossovers only if budget remains.

- [ ] **Step 5: Integrate into guard repair**

When guard-repair seeds are loaded into `frontier`, keep a `seed_sources_for_crossover`
list with label, source text, and protected hits. At each repair depth, generate
crossover probes once from that seed list and score them before subtractive and
generic probes. Record provenance and ledger entries through the existing
`candidate_probe_by_label` and `_score_candidate` path.

- [ ] **Step 6: Run focused crossover tests**

Run the red-test command again. Expected: both tests pass.

### Task 3: Frame/FPR Frontier Summary Fields

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing summary test**

Extend or add a test near `test_select_order_guard_repair_summary_reports_downhill_complement_ceiling`:

```python
def test_select_order_guard_repair_summary_includes_saved_register_deltas_for_fpr_frontier() -> None:
    force_phys = {32: 28, 33: 26, 38: 29, 39: 29}
    seed = {
        "label": "fpr-frame-hit",
        "status": "ok",
        "objective": {
            "force_phys_targets": {str(k): v for k, v in force_phys.items()},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 3,
            "force_phys_missing": [],
            "force_phys_mismatches": {"32": {"expected": 28, "actual": 26}},
            "force_phys_distance": 2,
            "frame_delta": 8,
        },
        "delta": {
            "saved_added": ["f29"],
            "saved_removed": [],
        },
        "structural_guard": {
            "accepted": False,
            "classification_primary": "stack-layout",
            "frame_delta": 8,
        },
    }

    summary = debug_cli._select_order_guard_repair_summary(
        [seed],
        force_phys=force_phys,
        function="fn_80000000",
    )

    candidate = summary["lanes"][0]["candidates"][0]
    assert candidate["saved_register_delta"] == {
        "saved_added": ["f29"],
        "saved_removed": [],
        "saved_fpr_added": ["f29"],
        "saved_fpr_removed": [],
    }
```

- [ ] **Step 2: Run red test**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_includes_saved_register_deltas_for_fpr_frontier
```

Expected: failure because summaries do not expose saved-register deltas.

- [ ] **Step 3: Implement saved-register summary helper**

Add:

```python
def _select_order_saved_register_delta(variant: Mapping[str, Any]) -> dict[str, list[str]]:
    delta = variant.get("delta")
    if not isinstance(delta, Mapping):
        return {"saved_added": [], "saved_removed": [], "saved_fpr_added": [], "saved_fpr_removed": []}
    added = [str(reg) for reg in delta.get("saved_added") or []]
    removed = [str(reg) for reg in delta.get("saved_removed") or []]
    return {
        "saved_added": added,
        "saved_removed": removed,
        "saved_fpr_added": [reg for reg in added if reg.startswith("f")],
        "saved_fpr_removed": [reg for reg in removed if reg.startswith("f")],
    }
```

Attach this field in `_select_order_guard_repair_candidate_summary`,
`_select_order_guard_repair_result_summary`, and
`_select_order_complement_candidate_summary` when variant data is available.

- [ ] **Step 4: Run summary test**

Run the red-test command again. Expected: pass.

### Task 4: Verification And Closure

**Files:**
- Modify: issue queue only after code is committed.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_select_order_search.py
```

Expected: all tests in both files pass.

- [ ] **Step 2: Run CLI smoke checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/mwcc_debug/pressure_explorer \
  tools/melee-agent/src/cli/debug
PYTHONPATH=tools/melee-agent python -m src.cli debug search structure --help >/tmp/structure-help.txt
PYTHONPATH=tools/melee-agent python -m src.cli debug select-order-search --help >/tmp/select-order-help.txt
```

Expected: all commands exit 0.

- [ ] **Step 3: Commit scoped files**

Stage only files for this work:

```bash
git add \
  docs/superpowers/specs/2026-06-18-compound-helper-and-crossover-repair-design.md \
  docs/superpowers/plans/2026-06-18-compound-helper-and-crossover-repair.md \
  tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_select_order_search.py
git commit -m "feat(melee-agent): add compound helper and crossover repair probes"
```

- [ ] **Step 4: Refresh editable install and resolve issues**

Run:

```bash
/opt/homebrew/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 809 --note "fixed in <commit>: condition-bool repeated-helper reuse ..."
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 810 --note "fixed in <commit>: retained source-hunk crossover repair ..."
DECOMP_AGENT_ID=codex-issue-resolver-3 melee-agent issue resolve 811 --note "fixed in <commit>: FPR/frame frontier crossover and saved-register summaries ..."
melee-agent issues list
git status --short
```

Expected: no open issues. Worktree may still show unrelated pre-existing dirty
files; do not stage or revert them.
