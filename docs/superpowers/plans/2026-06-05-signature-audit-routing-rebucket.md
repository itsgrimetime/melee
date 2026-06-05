# Signature Audit Routing And Rebucket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route signature-call-type queue rows to the new signature auditor and make signature-audit output either patch-candidate aware or explicitly rebucketed.

**Architecture:** Keep taxonomy routing in `tools/function_taxonomy_inventory.py` and keep source-level signature analysis in `tools/melee-agent/src/mwcc_debug/signature_audit.py`. Add summary/rebucket fields to existing dataclasses so CLI JSON continues to use `dataclasses.asdict(report)`.

**Tech Stack:** Python dataclasses, Typer CLI, pytest, existing `harvest.select_harness`, existing signature-audit synthetic assembly tests.

---

## File Structure

- Modify `tools/function_taxonomy_inventory.py`: change `signature-call-type` actionability and next command only.
- Modify `tools/melee-agent/tests/test_function_taxonomy_inventory.py`: update routing expectations and assert no registered harvest harness is selected.
- Modify `tools/melee-agent/src/mwcc_debug/signature_audit.py`: add `rebucket` and `summary`, compute summary after audit and after validation, and attach concrete rebucket metadata to fallback actions.
- Modify `tools/melee-agent/src/cli/debug.py`: print summary and rebucket details in text output; JSON should inherit fields from dataclasses.
- Modify `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`: add summary/rebucket unit tests.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: assert JSON and text output expose summary/rebucket metadata.

## Task 1: Taxonomy Routing

**Files:**
- Modify: `tools/function_taxonomy_inventory.py`
- Modify: `tools/melee-agent/tests/test_function_taxonomy_inventory.py`

- [ ] **Step 1: Write failing taxonomy tests**

Update `test_describe_actionability_splits_non_frame_work_buckets` so the
signature bucket expectation is:

```python
signature = describe_actionability("signature-call-type", "argument-bank")
assert signature["source_actionability"] == "current-tools-signature-audit"
assert signature["headline_tool"] == "debug-suggest-signatures"
assert "signature audit" in signature["actionability_reason"]
```

Add:

```python
def test_signature_call_type_next_command_routes_to_signature_audit() -> None:
    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == (
        "melee-agent debug suggest signatures -f fn_80000000 "
        "--source-file src/melee/demo/demo.c --json"
    )
```

Add:

```python
def test_signature_call_type_next_command_omits_empty_source_file() -> None:
    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == "melee-agent debug suggest signatures -f fn_80000000 --json"
```

Update the existing signature/inline queue test to assert signature rows are
visible to queue filtering but not harvest-executable:

```python
from src.harvest import HarvestFilters, load_queue_rows, select_harness

signature = load_queue_rows(
    queues / "signature-call-type.tsv",
    work_bucket="signature-call-type",
    repo_root=REPO_ROOT,
    filters=HarvestFilters(
        where={"source_actionability": ("current-tools-signature-audit",)}
    ),
)
assert len(signature) == 1
assert signature[0].headline_tool == "debug-suggest-signatures"
assert select_harness(signature[0]) is None
```

- [ ] **Step 2: Verify taxonomy tests fail for the old route**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_describe_actionability_splits_non_frame_work_buckets \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_signature_call_type_next_command_routes_to_signature_audit \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_signature_call_type_next_command_omits_empty_source_file \
  -q
```

Expected: failures showing `manual-signature-guidance`,
`debug-suggest-casts`, or a missing new test route.

- [ ] **Step 3: Implement the route**

Change only the `signature-call-type` branch:

```python
if bucket == "signature-call-type":
    return {
        "source_actionability": "current-tools-signature-audit",
        "headline_tool": "debug-suggest-signatures",
        "actionability_reason": (
            "call shape or prototype mismatch; run signature audit to inspect "
            "call-prep, prototypes, argument widths, and concrete rebucket reasons"
        ),
    }
```

Change `next_command()`:

```python
if bucket == "signature-call-type":
    if candidate.file_path:
        return (
            f"melee-agent debug suggest signatures -f {function} "
            f"--source-file {source_path} --json"
        )
    return (
        f"melee-agent debug suggest signatures -f {function} --json"
    )
```

- [ ] **Step 4: Verify taxonomy tests pass**

Run the same pytest command from Step 2. Expected: all selected tests pass.

## Task 2: Signature Audit Summary And Rebucket Model

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write failing signature-audit tests**

Add these assertions to
`test_audit_reports_unmatched_call_target_shape` immediately after the existing
`call-target-shape-audit` assertion:

```python
action = report.findings[0].actions[0]
assert action.kind == "call-target-shape-audit"
assert action.rebucket == {
    "reason": "call-offset-shift",
    "work_bucket": "structural-reconstruction",
    "subcategory": "call-target-shape",
    "explanation": (
        "The call target or ordinal differs; signature audit cannot "
        "produce a bounded type/prototype patch for this call shape."
    ),
}
assert report.summary["audit_only_unrebucketed"] == 0
assert report.summary["rebucket_reason_counts"]["call-offset-shift"] == 1
assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

Add:

```python
def test_audit_rebuckets_bank_mismatch_without_source_lever() -> None:
    source = """
void caller_fn(void)
{
    helper((f32) unknown_expr);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "prototype-candidate-missing"
    assert action.rebucket["subcategory"] == "argument-bank"
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

Add:

```python
def test_audit_rebuckets_argument_source_register_mismatch() -> None:
    source = """
void caller_fn(int arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r30",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "register-source-cascade"
    assert action.rebucket["work_bucket"] == "register-allocator"
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

Extend `test_audit_classifies_width_mismatch`:

```python
action = report.findings[0].actions[0]
assert action.rebucket["reason"] == "width-prototype-candidate-missing"
assert report.summary["rebucket_reason_counts"]["width-prototype-candidate-missing"] == 1
```

Extend `test_audit_suggests_removing_explicit_float_cast_for_gpr_target`:

```python
assert report.summary["patch_candidate_count"] == 1
assert report.summary["unvalidated_patch_candidate_count"] == 1
assert report.summary["validated_patch_candidate_count"] == 0
assert report.summary["stop_condition"]["kind"] == "unvalidated-patch-candidates"
```

Extend `test_audit_reports_same_tu_static_helper_prototype_without_patch`:

```python
assert report.summary["source_lever_action_count"] == 1
assert report.summary["audit_only_unrebucketed"] == 0
assert report.summary["stop_condition"]["kind"] == "source-lever-audit"
```

Extend `test_validate_signature_patch_attaches_candidate_delta` after
validation:

```python
assert report.summary["validated_patch_candidate_count"] == 1
assert report.summary["unvalidated_patch_candidate_count"] == 0
assert report.summary["stop_condition"]["kind"] == "validated-patch-candidates"
```

- [ ] **Step 2: Verify signature-audit tests fail before production code**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_reports_unmatched_call_target_shape \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_bank_mismatch_without_source_lever \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_argument_source_register_mismatch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_classifies_width_mismatch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_suggests_removing_explicit_float_cast_for_gpr_target \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_validate_signature_patch_attaches_candidate_delta \
  -q
```

Expected: failures for missing `rebucket`/`summary` fields.

- [ ] **Step 3: Implement dataclass fields and rebucket helpers**

Add fields:

```python
@dataclass
class SignatureAction:
    kind: str
    confidence: str
    affected_call_sites: list[dict]
    reason: str
    patch: PatchDescriptor | None = None
    validation: dict | None = None
    rebucket: dict[str, object] | None = None

@dataclass
class SignatureAuditReport:
    function: str
    classification: str | None
    findings: list[SignatureFinding]
    summary: dict[str, object] | None = None
```

Add helpers:

```python
def _rebucket(reason: str, work_bucket: str, subcategory: str, explanation: str) -> dict[str, object]:
    return {
        "reason": reason,
        "work_bucket": work_bucket,
        "subcategory": subcategory,
        "explanation": explanation,
    }
```

Use stable helper functions for call-target, argument-source, width/load, and
presence fallback actions. `argument-bank-mismatch` without a patch/prototype
source lever must map to `prototype-candidate-missing` with subcategory
`argument-bank`.

- [ ] **Step 4: Attach rebuckets to fallback audit actions**

In `_call_target_shape_findings()`, create `call-target-shape-audit` with
`rebucket=_call_target_rebucket(source_site, expected_call, current_call)`.

In `_actions_for_finding()`, create fallback `call-argument-type-audit` with
`rebucket=_argument_rebucket(finding.kind, source_site)`.

Do not attach rebucket metadata to `same-tu-static-prototype-audit`; it is a
bounded source-lever audit action.

- [ ] **Step 5: Compute and refresh summaries**

After `_merge_findings(findings)`, return:

```python
merged = _merge_findings(findings)
return SignatureAuditReport(
    function=str(payload.get("function") or function),
    classification=dict(payload.get("classification") or {}),
    findings=merged,
    summary=_summarize_report(merged),
)
```

At the end of `validate_signature_patches()`, set:

```python
report.summary = _summarize_report(report.findings)
```

The summary helper must count:

- actions with `patch`;
- actions with `patch` and validation status whose match is true or delta is
  positive;
- actions with `patch` and no improving validation;
- audit-only actions with `rebucket`;
- audit-only actions without `rebucket` and without source-lever kind.

The stop-condition precedence must be:

1. `no-findings`
2. `validated-patch-candidates`
3. `unvalidated-patch-candidates`
4. `audit-only-unclassified`
5. `source-lever-audit`
6. `rebucketed-audit-only`

- [ ] **Step 6: Verify signature-audit tests pass**

Run the same pytest command from Step 2. Expected: all selected tests pass.

## Task 3: CLI JSON And Text Output

**Files:**
- Modify: `tools/melee-agent/src/cli/debug.py`
- Modify: `tools/melee-agent/tests/test_debug_cli_reorg.py`

- [ ] **Step 1: Write failing CLI tests**

Extend `test_debug_suggest_signatures_json_from_saved_checkdiff`:

```python
assert report["summary"]["patch_candidate_count"] == 1
assert report["summary"]["stop_condition"]["kind"] == "unvalidated-patch-candidates"
assert action["rebucket"] is None
```

Add a text-output test using call target mismatch:

```python
def test_debug_suggest_signatures_text_prints_summary_and_rebucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        "void caller_fn(int value) { helper_b(value); }\n",
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(json.dumps({
        "function": "caller_fn",
        "classification": {"primary": "signature-type-mismatch"},
        "target_asm": ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper_a"],
        "current_asm": ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper_b"],
        "fuzzy_match_percent": 97.5,
    }))
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/demo")

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "stop: rebucketed-audit-only" in result.output
    assert "rebucket: call-offset-shift -> structural-reconstruction/call-target-shape" in result.output
```

- [ ] **Step 2: Verify CLI tests fail before text implementation**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_summary_and_rebucket \
  -q
```

Expected: text test missing output; JSON summary may already pass after Task 2.

- [ ] **Step 3: Print summary and rebucket text**

In `_print_signature_report()`, before listing findings:

```python
summary = report.summary or {}
stop = summary.get("stop_condition") or {}
if stop:
    print(
        f"stop: {stop.get('kind')} "
        f"(patches={summary.get('patch_candidate_count', 0)}, "
        f"rebucketed={summary.get('rebucketed_audit_only_count', 0)}, "
        f"unrebucketed={summary.get('audit_only_unrebucketed', 0)})"
    )
```

When printing each action:

```python
if action.rebucket:
    print(
        f"      rebucket: {action.rebucket['reason']} -> "
        f"{action.rebucket['work_bucket']}/{action.rebucket['subcategory']}"
    )
    print(f"        {action.rebucket['explanation']}")
```

- [ ] **Step 4: Verify CLI tests pass**

Run the same pytest command from Step 2. Expected: both selected tests pass.

## Task 4: Focused Verification And Commit

**Files:**
- All files changed by Tasks 1-3.

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_summary_and_rebucket \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run syntax and command smoke checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  tools/function_taxonomy_inventory.py \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures --help
```

Expected: py_compile exits 0 and help shows the `suggest signatures` options.

- [ ] **Step 3: Check worktree and whitespace**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended files are modified/untracked.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/superpowers/specs/2026-06-05-signature-audit-routing-rebucket-design.md \
  docs/superpowers/plans/2026-06-05-signature-audit-routing-rebucket.md \
  tools/function_taxonomy_inventory.py \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "Route signature audit findings to actionable rebuckets"
```

Expected: commit succeeds on `master`.

- [ ] **Step 5: Refresh editable CLI install**

Run from `/Users/mike/code/melee`:

```bash
python -m pip install -e tools/melee-agent
/opt/homebrew/bin/melee-agent debug suggest signatures --help
python - <<'PY'
import pathlib
import src.cli.debug as debug
print(pathlib.Path(debug.__file__).resolve())
PY
```

Expected: help succeeds and the import path is under
`/Users/mike/code/melee/tools/melee-agent/src`.

- [ ] **Step 6: Resolve issues #429 and #430**

Run:

```bash
melee-agent issue resolve 429 --note "fixed in <commit>: signature-call-type rows now route to debug suggest signatures"
melee-agent issue resolve 430 --note "fixed in <commit>: signature auditor now emits summary stop conditions and concrete rebucket reasons for audit-only actions"
melee-agent issue list --status open
```

Expected: only intentionally open tracking/data-gathering issues remain, or no
open issues.
