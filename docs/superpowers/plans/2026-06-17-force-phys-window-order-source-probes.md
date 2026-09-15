# Force-Phys Window-Order Source Probes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add force-phys-aware source probes from solver window-order fallback leads and compose them with transform-corpus probes in `debug select-order-search` beam mode.

**Architecture:** A new reusable helper materializes conservative statement-move probes from normalized fallback leads. The CLI computes fallback leads in force-phys mode, adds them to JSON diagnostics, appends helper probes to single-probe runs, expands transform-corpus plus helper probes in beam rounds, and uses objective-first ranking only when force-phys proof targets are present.

**Tech Stack:** Python, Typer CLI, pytest, existing `LifetimeLayoutProbe`, `statement_move`, and transform-corpus adapters.

---

### Task 1: Window-Order Source Probe Helper

**Files:**
- Create: `tools/melee-agent/src/search/directed/window_order_source.py`
- Test: `tools/melee-agent/tests/search/directed/test_window_order_source.py`

- [ ] **Step 1: Write failing helper tests**

Add tests that build small C functions and fallback leads:

```python
def test_window_order_probe_hoists_unique_source_local():
    source = '''
    void fn(void) {
        int idx;
        int guard;
        int dst_iter;
        idx = guard;
        dst_iter = idx;
        guard = dst_iter;
    }
    '''
    leads = [{
        "target_ig": 34,
        "order_move": ["before", 43],
        "move_distance": 5,
        "perturbed_reg": 25,
    }]
    attrs = {34: {"kind": "local", "name": "dst_iter", "source_line": 6}}
    probes = generate_window_order_source_probes(
        source, function="fn", fallback_leads=leads,
        source_attributions=attrs, max_probes=4,
    )
    assert probes
    assert probes[0].operator == "window-order-source-steering"
    assert probes[0].provenance["lead"]["target_ig"] == 34
    assert "dst_iter = idx;" in probes[0].source_text
```

Also test that missing attribution and duplicated movable units emit no probes.

- [ ] **Step 2: Run helper tests and confirm red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: import failure for `src.search.directed.window_order_source`.

- [ ] **Step 3: Implement helper**

Implement:

```python
def generate_window_order_source_probes(
    source_text: str,
    *,
    function: str,
    fallback_leads: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Mapping[str, Any]] | None = None,
    max_probes: int = 8,
) -> list[LifetimeLayoutProbe]:
    ...
```

Use `statement_move.sibling_groups`, `extract_movable_units`,
`legal_destinations`, and `apply_move`. Bind each lead by
`source_attributions[target_ig]["name"]`. Require exactly one movable unit with
that `write_base`. For `["before", anchor]`, choose legal destinations less
than the unit start. For `["after", anchor]`, choose legal destinations greater
than the unit end. Return probes with provenance containing `kind`,
`lead`, `source_attribution`, `moved_local`, `scope_depth`, `destination`, and
`line_range`.

- [ ] **Step 4: Run helper tests and confirm green**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/search/directed/test_window_order_source.py -q
```

Expected: all helper tests pass.

### Task 2: Select-Order CLI Integration

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests that monkeypatch:

- `_register_tiebreak_window_order_fallback` to return one lead.
- `generate_window_order_source_probes` to return a synthetic
  `LifetimeLayoutProbe`.
- `generate_transform_probes` or `_append_transform_corpus_probes` path so beam
  mode has a transform-corpus first step.

Assertions:

- JSON includes `window_order_fallback`.
- `--no-compile-probes --json` lists `window-order-source-steering` probes.
- Beam mode records transform-corpus then window-order probes in the chain.
- With `--transform-force-phys`, a lower-match candidate with higher
  `force_phys_satisfied_count` ranks above a higher-match wrong-phys candidate.
- Existing no-force beam real-score ranking remains unchanged.

- [ ] **Step 2: Run targeted CLI tests and confirm red**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: new tests fail because fallback probes are not emitted and beam mode
does not expand transform-corpus probes.

- [ ] **Step 3: Implement CLI orchestration**

In `debug_select_order_search_cmd`:

- Parse `proof_force_map` as today.
- When `transform_force_phys` is present, call
  `_register_tiebreak_window_order_fallback(function=function, class_id=class_id)`.
- Derive source attribution for lead targets from available pcdump data when
  possible and pass it to `generate_window_order_source_probes`.
- Append helper probes after transform-corpus probes and before generic
  lifetime probes, respecting `max_probes`.
- In beam rounds, generate per-parent probes from:
  `generate_lifetime_layout_probes`, `_transform_corpus_lifetime_probes`, and
  `generate_window_order_source_probes`.
- Rank beam frontier/final variants with `rank_select_order_candidates` when
  `proof_force_map` is non-empty; keep `_rank_select_order_candidates_real_first`
  otherwise.
- Emit `window_order_fallback` and `window_order_probe_diagnostics` additively in
  JSON and beam ledger.

- [ ] **Step 4: Run targeted CLI tests and confirm green**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: all select-order tests pass.

### Task 3: Smoke, Install Refresh, Resolve Issues

**Files:**
- Modify only if needed: `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] **Step 1: Run narrow tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_window_order_source.py \
  tools/melee-agent/tests/test_select_order_search.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run command-level smoke checks**

Run a no-compile JSON smoke:

```bash
PYTHONPATH=tools/melee-agent melee-agent debug select-order-search \
  -f mnDiagram_DrawCellNumber \
  --class 1 \
  --target f33<f39 \
  --transform-force-phys 39:26,33:28 \
  --max-probes 8 \
  --no-compile-probes \
  --json
```

Expected: exit 0 and JSON includes `window_order_fallback`.

- [ ] **Step 3: Commit only feature files/hunks**

Stage the new design, plan, helper, helper tests, and the exact CLI/test hunks.
Do not stage unrelated dirty edits in solver or wording changes.

- [ ] **Step 4: Refresh editable install**

Run:

```bash
python -m pip install -e tools/melee-agent
cd /tmp && python - <<'PY'
import src.cli.debug as debug_cli
import src.search.directed.window_order_source as wos
print(debug_cli.__file__)
print(wos.__file__)
PY
/opt/homebrew/bin/melee-agent --help
```

Expected: imports point at `/Users/mike/code/melee/tools/melee-agent`.

- [ ] **Step 5: Resolve issues**

Resolve #749 and #750 with notes referencing the commit hash. Leave unrelated
or still-blocked issues open.
