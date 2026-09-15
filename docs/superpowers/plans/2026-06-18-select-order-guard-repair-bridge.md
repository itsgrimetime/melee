# Select-Order Guard Repair Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #789 and #790 by making `debug select-order-search --json` explain guarded allocator-hit repair lanes and source-actionable GPR order bridges.

**Architecture:** Add a bounded guard-repair pass inside `debug select-order-search` after the normal beam, seeded from rejected allocator-hit variants with retained source. Add pure summary helpers beside the existing select-order CLI helpers, then call them after variants are ranked and diagnostic buckets are available. The normal beam and ranking behavior remain unchanged; repair candidates are additional variants and ledger entries.

**Tech Stack:** Python, Typer CLI, pytest, existing `mwcc_debug.select_order_search` and source-directed probe metadata.

---

### Task 1: Guard Repair Seed Selection and Summary

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing helper test**

Add `test_select_order_guard_repair_summary_groups_rejected_allocator_hits` to `tools/melee-agent/tests/test_select_order_search.py`. The test should build three ranked variant dictionaries:

```python
variants = [
    {
        "label": "inline-hit",
        "status": "ok",
        "path": "/tmp/inline-hit.c",
        "source_retained": "/tmp/inline-hit.c",
        "chain": ["coloring_register_steering-3"],
        "objective": {
            "force_phys_targets": {"32": 28, "33": 26},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_mismatches": {"33": {"expected": 26, "actual": 27}},
            "force_phys_missing": [],
            "force_phys_distance": 1,
            "match_percent": 93.49,
            "frame_delta": 0,
        },
        "structural_guard": {
            "accepted": False,
            "rejection_reason": "inline-boundary-toolchain-artifact",
            "classification_primary": "structural",
            "normalized_diff_lines": 21,
            "frame_delta": 0,
        },
    },
    {
        "label": "stack-hit",
        "status": "ok",
        "path": "/tmp/stack-hit.c",
        "source_retained": "/tmp/stack-hit.c",
        "chain": ["lifetime-layout"],
        "objective": {
            "force_phys_targets": {"32": 26, "33": 26},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 1,
            "force_phys_mismatches": {"33": {"expected": 27, "actual": 26}},
            "force_phys_missing": [],
            "force_phys_distance": 1,
            "match_percent": 99.43,
            "frame_delta": 8,
        },
        "structural_guard": {
            "accepted": False,
            "rejection_reason": "stack-layout frame_delta=8",
            "classification_primary": "structural",
            "normalized_diff_lines": 0,
            "frame_delta": 8,
        },
    },
    {
        "label": "plain-miss",
        "status": "ok",
        "objective": {
            "force_phys_targets": {"32": 28, "33": 26},
            "force_phys_satisfied": False,
            "force_phys_satisfied_count": 0,
            "force_phys_mismatches": {},
            "force_phys_missing": [32, 33],
            "force_phys_distance": 2000,
        },
        "structural_guard": {"accepted": True},
    },
]
summary = debug_cli._select_order_guard_repair_summary(variants, force_phys={32: 28, 33: 26})
assert summary["status"] == "needs-repair"
assert [lane["guard_class"] for lane in summary["lanes"]] == ["inline-boundary-toolchain-artifact", "stack-layout"]
assert summary["lanes"][0]["repair_action"]["kind"] == "restore-inline-boundary-shape"
assert summary["lanes"][1]["repair_action"]["kind"] == "repair-stack-layout"
assert summary["lanes"][0]["candidates"][0]["achieved_registers"]["32"] == 28
assert summary["seed_count"] == 2
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_groups_rejected_allocator_hits -q
```

Expected: fail with `AttributeError` for the missing helper.

- [ ] **Step 3: Implement the helper**

In `tools/melee-agent/src/cli/debug/__init__.py`, add helpers near `_select_order_diagnostic_buckets`:

```python
def _select_order_guard_repair_summary(
    ranked_variants: list[Mapping[str, Any]],
    *,
    force_phys: Mapping[int, int],
    max_lanes: int = 4,
    max_candidates_per_lane: int = 3,
) -> dict[str, Any]:
    ...
```

The implementation must:

- Return `{"status": "not-requested", "lanes": []}` when `force_phys` is empty.
- Select only ok variants with `structural_guard.accepted is False`, `objective.force_phys_satisfied_count > 0`, and a retained source path when repair seeding is requested.
- Classify guard reasons containing `inline-boundary` as `inline-boundary-toolchain-artifact`, reasons containing `stack` or nonzero `frame_delta` as `stack-layout`, and everything else as `structural-drift`.
- Include candidate fields: `label`, `rank`, `path`, `source_retained`, `chain`, `match_percent`, `force_phys_satisfied_count`, `force_phys_distance`, `achieved_registers`, `missing_registers`, `mismatched_registers`, `guard`, `normalized_diff_lines`, and `frame_delta`.
- Sort lanes by best candidate count, then force-phys distance, then negative match percent.
- Attach `repair_action.kind` values `restore-inline-boundary-shape`, `repair-stack-layout`, or `inspect-structural-drift`, each with a short `next_command_hint` using `debug select-order-search --candidate`.
- Return `status == "needs-repair"` when any lane exists, otherwise `status == "no-guarded-allocator-hit"`.

- [ ] **Step 4: Verify the helper**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_guard_repair_summary_groups_rejected_allocator_hits -q
```

Expected: pass.

### Task 2: Guard Repair Beam

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing beam test**

Add `test_select_order_search_guard_repair_beam_expands_rejected_allocator_hit` to `tools/melee-agent/tests/test_select_order_search.py`. Use the existing fake compile/scoring pattern:

```python
baseline = tmp_path / "baseline.txt"
source = tmp_path / "sample.c"
campaign = tmp_path / "campaign"
seed = tmp_path / "seed.c"
baseline.write_text(BASELINE)
source.write_text("void fn_80000000(void) { /* base */ }\n")
seed.write_text("void fn_80000000(void) { /* rejected-hit */ }\n")

def fake_probes(current_source: str, *args, **kwargs):
    if "rejected-hit" not in current_source:
        return []
    return [LifetimeLayoutProbe(
        label="repair-shape",
        operator="block-scope",
        description="Synthetic guard repair.",
        source_text=current_source.replace("rejected-hit", "rejected-hit repaired"),
    )]

def fake_compile(diff_input, **kwargs):
    if "repaired" in diff_input.path.read_text():
        return TARGET_ORDER_RIGHT_PHYS
    return TARGET_ORDER_RIGHT_PHYS

class FakeScore:
    def __init__(self, path):
        text = pathlib.Path(path).read_text()
        self.match_percent = 98.0 if "repaired" in text else 93.0
        self.match_percent_error = None
        self.structural_guard_error = None
        self.structural_guard = {
            "accepted": "repaired" in text,
            "rejection_reason": None if "repaired" in text else "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 0 if "repaired" in text else 21,
            "frame_delta": 0,
        }

monkeypatch.setattr("src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes", fake_probes)
monkeypatch.setattr("src.mwcc_debug.diff_capture.compile_source_variant", fake_compile)
monkeypatch.setattr("src.cli.debug._select_order_source_score", lambda path, **kwargs: FakeScore(path))
result = runner.invoke(app, [
    "debug", "select-order-search",
    "-f", "fn_80000000",
    "--target", "r32<r33",
    "--pcdump", str(baseline),
    "--source-file", str(source),
    "--candidate", f"seed:shape={seed}",
    "--transform-force-phys", "32:29",
    "--guard-repair-depth", "1",
    "--guard-repair-width", "1",
    "--campaign-dir", str(campaign),
    "--no-compile-probes",
    "--json",
])
payload = json.loads(result.stdout)
assert result.exit_code == 0, result.stdout + result.stderr
assert payload["guard_repair_ledger"]
ledger = json.loads(pathlib.Path(payload["guard_repair_ledger"]).read_text())
assert ledger["seeds"][0]["label"] == "seed"
assert ledger["entries"][0]["seed_label"] == "seed"
assert payload["guard_repair_summary"]["status"] in {"repaired", "needs-repair"}
assert any("repair-shape" in variant.get("label", "") for variant in payload["variants"])
```

- [ ] **Step 2: Verify the beam test fails**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_guard_repair_beam_expands_rejected_allocator_hit -q
```

Expected: fail because the CLI lacks guard-repair options and ledger output.

- [ ] **Step 3: Implement the bounded repair pass**

Add CLI options to `select_order_search_cmd`:

```python
guard_repair_depth: Annotated[
    Optional[int],
    typer.Option("--guard-repair-depth", help="Depth for guarded repair beam; omitted auto-enables depth 1 for force-phys beam mode."),
] = None,
guard_repair_width: Annotated[int, typer.Option("--guard-repair-width", help="Rejected allocator-hit seeds to repair per round.")] = 2,
```

Validate nonnegative depth and positive width. Use effective depth:

```python
effective_guard_repair_depth = (
    guard_repair_depth
    if guard_repair_depth is not None
    else (1 if proof_force_map and beam_depth > 0 else 0)
)
```

After the normal beam loop and before final ranking:

- Rank current variants to choose repair seeds with `_select_order_guard_repair_seed_variants`.
- Create `guard-repair` under `campaign_dir` or a temp directory.
- For each seed, read `source_retained`, record protected force-phys hits, and generate `_generated_select_order_probes_for(seed_source, include_lifetime=True, max_count=max_probes)`.
- Score each generated repair source through `_score_candidate`, setting `parent_label`, `chain`, and an added `repair_seed_label` field on the returned variant.
- Record ledger `seeds`, `entries`, `deduped`, `stop_condition`, `effective_depth`, and `width`.
- Select the next repair frontier by guard accepted first, protected hit count, lower normalized diff lines, lower absolute frame delta, lower force-phys distance, then higher match percent.

Do not mutate normal beam ranking or remove rejected seed variants.

- [ ] **Step 4: Verify the beam**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_guard_repair_beam_expands_rejected_allocator_hit -q
```

Expected: pass.

### Task 3: Source Bridge Summary

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing helper test**

Add `test_select_order_source_bridge_summary_explains_order_leads_and_blockers` to `tools/melee-agent/tests/test_select_order_search.py`:

```python
fallback = {
    "ran": True,
    "leads": [
        {"target_ig": 34, "order_move": ["before", 43], "move_distance": 10, "perturbed_reg": 27},
        {"target_ig": 44, "order_move": ["after", 34], "move_distance": 4, "perturbed_reg": 25},
    ],
}
attrs = {
    34: {"kind": "local", "name": "j", "source_file": "src/melee/mn/mndiagram.c", "source_line": 1234, "confidence": "high"},
}
diagnostics = {
    "fallback_leads": 2,
    "source_attributed_leads": 1,
    "listed_source_probes": 0,
}
variants = [
    {
        "label": "indexed-byte",
        "status": "ok",
        "operator": "transform-corpus:indexed_byte_address_temp_steering",
        "objective": {
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied_count": 0,
            "force_phys_mismatches": {"34": {"expected": 27, "actual": 25}, "44": {"expected": 25, "actual": 28}},
            "force_phys_missing": [],
            "force_phys_distance": 5,
            "frame_delta": 0,
            "match_percent": 99.3,
        },
        "structural_guard": {"accepted": True},
    },
    {
        "label": "pad-stack",
        "status": "ok",
        "operator": "lifetime-layout",
        "objective": {
            "force_phys_targets": {"34": 27, "44": 25},
            "force_phys_satisfied_count": 1,
            "force_phys_mismatches": {"34": {"expected": 27, "actual": 24}},
            "force_phys_missing": [],
            "force_phys_distance": 3,
            "frame_delta": 8,
            "match_percent": 99.1,
        },
        "structural_guard": {"accepted": False, "rejection_reason": "stack-layout frame_delta=8"},
    },
]
summary = debug_cli._select_order_source_bridge_summary(
    ranked_variants=variants,
    force_phys={34: 27, 44: 25},
    window_order_fallback=fallback,
    window_order_source_attributions=attrs,
    window_order_probe_diagnostics=diagnostics,
    diagnostic_buckets={},
)
assert summary["status"] == "blocked"
assert summary["dominant_blocker"] == "window-order-leads-not-materialized"
assert summary["leads"][0]["source"]["name"] == "j"
assert summary["leads"][1]["source"] is None
assert "indexed-byte-address-temp-shape" in summary["blocker_classes"]
assert "stack-layout" in summary["blocker_classes"]
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_summary_explains_order_leads_and_blockers -q
```

Expected: fail with `AttributeError` for the missing helper.

- [ ] **Step 3: Implement the helper**

In `tools/melee-agent/src/cli/debug/__init__.py`, add:

```python
def _select_order_source_bridge_summary(
    *,
    ranked_variants: list[Mapping[str, Any]],
    force_phys: Mapping[int, int],
    window_order_fallback: Mapping[str, Any] | None,
    window_order_source_attributions: Mapping[int, Any] | Mapping[str, Any],
    window_order_probe_diagnostics: Mapping[str, Any],
    diagnostic_buckets: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    ...
```

The implementation must:

- Return `{"status": "not-requested", "leads": [], "blocker_classes": []}` when `force_phys` is empty.
- Preserve each fallback lead with `target_ig`, `order_move`, `move_distance`, `perturbed_reg`, and source attribution serialized by `_solve_source_attribution_dict`.
- Count materialized source probes using `window_order_probe_diagnostics.listed_source_probes`.
- Extract achieved registers from each variant objective’s `force_phys_targets`, `force_phys_mismatches`, and missing list.
- Classify blocker classes from operator names and guard/objective facts:
  `indexed-byte-address-temp-shape`, `stack-layout`, `declaration-lifetime-order`, `guard-rejected-structural-drift`, `unscored-or-build-failed`, and `wrong-register`.
- Do not broaden `window_order_source` movement rules. Missing or unsafe source probes must be represented as explanation, not guessed edits.
- Set `dominant_blocker` to `window-order-leads-not-materialized` when fallback leads exist but source probes are zero, `source-probes-exhausted` when probes exist but no exact force-phys candidate exists, `terminal-allocator-ceiling` when no leads exist and all candidates are wrong-register, or `resolved` when a force-phys-satisfied candidate exists.
- Include `ranked_actions` entries for attributed leads and for dominant blocker classes, using action kinds such as `try-window-order-source-move`, `inspect-indexed-byte-address-temp-shape`, `repair-stack-layout`, `adjust-declaration-lifetime-order`, and `record-terminal-allocator-ceiling`.

- [ ] **Step 4: Verify the helper**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_source_bridge_summary_explains_order_leads_and_blockers -q
```

Expected: pass.

### Task 4: JSON and Text Integration

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] **Step 1: Write the failing command test**

Add `test_select_order_search_json_includes_guard_repair_and_source_bridge_summaries`. Use existing monkeypatch patterns in this test file:

- Patch `_register_tiebreak_window_order_fallback` to return one lead.
- Patch `_select_order_source_attributions_for_leads` to return one local attribution.
- Patch `generate_lifetime_layout_probes` to return no probes.
- Patch `compile_source_variant` so a candidate pcdump gives one wrong-register result.
- Patch `_select_order_source_score` so the candidate carries a rejected structural guard.
- Invoke `debug select-order-search --transform-force-phys 32:29 --candidate hit:shape=/tmp/hit.c --guard-repair-depth 0 --no-compile-probes --json`.
- Assert JSON has `guard_repair_summary.status == "needs-repair"`, `source_bridge_summary.status` in `{"blocked", "needs-source-probes", "resolved"}`, and `guard_repair_ledger is None`.

- [ ] **Step 2: Verify the command test fails**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_json_includes_guard_repair_and_source_bridge_summaries -q
```

Expected: fail because the JSON payload lacks the new keys.

- [ ] **Step 3: Wire summaries into command output**

After `diagnostic_buckets` is computed and before JSON emission, compute:

```python
guard_repair_summary = _select_order_guard_repair_summary(
    ranked_variants,
    force_phys=proof_force_map or {},
    guard_repair_ledger=guard_repair_ledger,
)
source_bridge_summary = _select_order_source_bridge_summary(
    ranked_variants=ranked_variants,
    force_phys=proof_force_map or {},
    window_order_fallback=window_order_fallback,
    window_order_source_attributions=window_order_source_attributions,
    window_order_probe_diagnostics=window_order_probe_diagnostics,
    diagnostic_buckets=diagnostic_buckets,
)
```

Add both keys to the JSON payload. For text output, print a short summary only when a section status is actionable:

```text
guard repair: needs-repair (inline-boundary-toolchain-artifact, stack-layout)
source bridge: blocked via window-order-leads-not-materialized
```

Do not change ranking, variant schema, probe generation, or beam ledger schema.

- [ ] **Step 4: Verify integration**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py::test_select_order_search_json_includes_guard_repair_and_source_bridge_summaries -q
```

Expected: pass.

### Task 5: Verification, Install Refresh, and Issue Resolution

**Files:**
- Commit all modified source, tests, spec, and plan files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_select_order_search.py -q
```

Expected: pass.

- [ ] **Step 2: Run smoke checks**

Run:

```bash
python -m py_compile tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/mwcc_debug/select_order_search.py
melee-agent debug select-order-search --help >/tmp/select-order-help.txt
melee-agent issue show 789 >/tmp/issue-789.txt
melee-agent issue show 790 >/tmp/issue-790.txt
```

Expected: all commands exit 0.

- [ ] **Step 3: Refresh editable install**

Run from `/Users/mike/code/melee`:

```bash
python -m pip install -e tools/melee-agent
/opt/homebrew/bin/melee-agent issues list >/tmp/melee-agent-issues-after-install.txt
```

Expected: editable install succeeds and `/opt/homebrew/bin/melee-agent` runs from current `master`.

- [ ] **Step 4: Commit and resolve issues**

Stage only files touched for this work:

```bash
git add docs/superpowers/specs/2026-06-18-select-order-guard-repair-bridge-design.md \
  docs/superpowers/plans/2026-06-18-select-order-guard-repair-bridge.md \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/tests/test_select_order_search.py
git commit -m "Add select-order guard repair bridge diagnostics"
melee-agent issue resolve 789 --note "Fixed by guard_repair_summary in <commit>; rejected allocator-hit candidates now produce inline-boundary and stack-layout repair lanes with retained source paths and register facts."
melee-agent issue resolve 790 --note "Fixed by source_bridge_summary in <commit>; window-order leads now map to source attributions/actions or terminal allocator-ceiling blocker classes."
```

Expected: commit succeeds, both issues resolve, and `git status --short` shows only unrelated pre-existing dirty files if they are still present.
