# Taxonomy Struct Offset Resolver Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve #455 by keeping taxonomy `struct-offset-discrepancy` rows only when `struct verify` proves named, non-ambiguous struct fields.

**Architecture:** Add a pluggable struct-verify gate to `tools/function_taxonomy_inventory.py`. The gate runs only after the existing checkdiff bucket heuristic selects `struct-offset-discrepancy`, attaches evidence fields, rebuckets successful resolver-negative rows to `data-symbol-relocation`, and leaves unavailable resolver runs in the legacy heuristic bucket.

**Tech Stack:** Python 3.11, subprocess JSON runners, pytest, existing `melee-agent struct verify` CLI.

---

Spec: `docs/superpowers/specs/2026-06-06-taxonomy-struct-offset-resolver-gate-design.md`
Issue: #455

## Files

- Modify: `tools/function_taxonomy_inventory.py`
- Modify: `tools/melee-agent/tests/test_function_taxonomy_inventory.py`
- Create: `docs/superpowers/specs/2026-06-06-taxonomy-struct-offset-resolver-gate-design.md`
- Create: `docs/superpowers/plans/2026-06-06-taxonomy-struct-offset-resolver-gate.md`

## Task 1 - Struct Verify Runner and Command Construction

- [x] Add tests in `tools/melee-agent/tests/test_function_taxonomy_inventory.py` for a new `_struct_verify_command(candidate, classification)` helper.
  Cover:
  - one unique raw base emits `["melee-agent", "struct", "verify", function, "--base", base, "--tu-src", source, "--json"]`
  - multiple bases omit `--base`
- [x] Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py -q -k 'struct_verify_command'
```

Expected: fail because the helper does not exist.

- [x] In `tools/function_taxonomy_inventory.py`, add:

```python
DEFAULT_STRUCT_VERIFY_TIMEOUT = 180.0
StructVerifyRunner = Callable[[FunctionCandidate, dict[str, Any]], dict[str, Any] | None]
```

- [x] Implement `_struct_verify_command(candidate, classification) -> list[str]` using `offset_discrepancy_summary(classification)` and `src/{candidate.file_path}`.
- [x] Implement `default_struct_verify_runner(candidate, classification, *, timeout=DEFAULT_STRUCT_VERIFY_TIMEOUT)`.
  It should call the command with `subprocess.run(..., timeout=timeout, capture_output=True, text=True, cwd=REPO_ROOT)`, return `None` on timeout, nonzero returncode, empty stdout, or invalid JSON, and return `parse_json_object(proc.stdout)` on success.
- [x] Re-run the focused command tests and verify they pass.

## Task 2 - Gate Payload Classification

- [x] Add tests for pure helpers:
  - verified payload with `{"struct": "Fake", "field": "x0", "conflict": false, "ambiguous": false}` reports verified with struct/field evidence
  - empty findings plus `auto-struct unresolved` skip reports unverified
  - all-ambiguous or all-conflicting findings report unverified
  - missing `struct` or `field` reports unverified
  - `None`, invalid/unavailable runner marker, or skip reason `checkdiff failed` reports unavailable
- [x] Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py -q -k 'struct_verify_gate'
```

Expected: fail because the helpers do not exist.

- [x] Implement:

```python
def _verified_struct_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ...

def summarize_struct_verify_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    ...
```

Summary keys:

```python
{
    "struct_verify_status": "verified" | "unverified" | "unavailable",
    "struct_verify_finding_count": int,
    "struct_verify_verified_count": int,
    "struct_verify_structs": str,
    "struct_verify_fields": str,
    "struct_verify_skipped": str,
    "struct_verify_reason": str,
}
```

- [x] Treat payload `None` as unavailable.
- [x] Treat successful payloads with verified findings as verified.
- [x] Treat successful payloads with only resolver-negative skips as unverified.
- [x] Treat successful payloads with no verified findings and unavailable skip reasons such as `checkdiff failed` or `source read failed` as unavailable.
- [x] Re-run the focused gate tests and verify they pass.

## Task 3 - Attach Gate to Classification

- [x] Add classify-candidate tests:
  - raw offset row plus verified payload stays in `struct-offset-discrepancy`, has `confidence == "resolver-verified"`, and includes `struct_verify_*` evidence
  - raw offset row plus unverified payload rebuckets to `data-symbol-relocation`, has `subcategory == "unverified-struct-offset-displacement"`, `confidence == "resolver-rebucketed"`, and keeps `offset_discrepancy_*`
  - raw offset row plus unavailable payload stays in `struct-offset-discrepancy` with `confidence == "heuristic"` and `struct_verify_status == "unavailable"`
  - `struct_verify_runner=None` preserves legacy heuristic struct-offset behavior
- [x] Run the classify-candidate focused tests and verify they fail.
- [x] Add a `struct_verify_runner` parameter to `classify_candidate()`, defaulting to `default_struct_verify_runner`.
- [x] After offset summary is attached, call the runner only when `record["work_bucket"] == "struct-offset-discrepancy"`.
- [x] Implement `attach_struct_verify_gate(record, candidate, classification, payload_or_none)`:
  - update evidence fields from `summarize_struct_verify_payload()`
  - if status is `verified`, keep the bucket and set `confidence = "resolver-verified"`
  - if status is `unverified`, set bucket/subcategory/confidence to data-symbol rebucket values and recompute actionability plus `next_command`
  - if status is `unavailable`, keep the bucket and existing actionability
- [x] Move name-magic preflight so it runs after the struct gate whenever the final bucket is `data-symbol-relocation`.
- [x] Re-run the classify-candidate tests and verify they pass.

## Task 4 - Output Columns and CLI Plumbing

- [x] Add serializer tests:
  - `write_csv()` output contains `struct_verify_status`, `struct_verify_verified_count`, `struct_verify_structs`, `struct_verify_fields`, and `struct_verify_reason`
  - `write_queue()` output contains the same fields
- [x] Add generate/main tests:
  - `generate_inventory(..., struct_verify_runner=fake)` uses the fake runner and writes evidence to queue TSV
  - `generate_inventory(..., struct_verify_runner=None)` preserves legacy behavior
  - `main(["--skip-struct-verify-gate", ...])` passes `None` for the runner
- [x] Run the serializer and CLI plumbing tests and verify they fail.
- [x] Add the `struct_verify_*` fields to `write_csv()` and `write_queue()`.
- [x] Add a `struct_verify_runner` parameter to `generate_inventory()` and thread it through the executor `classify_candidate()` call.
- [x] Add `--skip-struct-verify-gate` and `--struct-verify-timeout` to `build_arg_parser()`.
- [x] In `main()`, pass `None` for skip mode; otherwise pass a lambda calling `default_struct_verify_runner(candidate, classification, timeout=struct_verify_timeout)`.
- [x] Re-run the focused output/plumbing tests and verify they pass.

## Task 5 - Verification, Review, Commit, Resolve

- [x] Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py -q
python -m py_compile tools/function_taxonomy_inventory.py
git diff --check
```

- [x] Run command smoke:

```bash
python tools/function_taxonomy_inventory.py --limit 1 --workers 1 --output build/function-taxonomy-smoke --struct-verify-timeout 30
```

- [x] Request independent Codex review of the implementation.
- [x] Fix any review blockers and rerun the relevant tests.
- [x] Mark this plan complete by changing all checkboxes to `[x]`.
- [x] Commit only the #455 spec, plan, code, and tests.
- [x] Resolve issue #455 with the commit hash.
