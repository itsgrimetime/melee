# Signature Prototype Source-Lever Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug suggest signatures` emit executable prototype candidates only when a real type/patch lever exists, and rebucket diagnostic prototype context with concrete reasons.

**Architecture:** Add a bounded prototype-decision helper in `signature_audit.py` that separates executable candidates from diagnostic context. Preserve existing patch validation for patch-bearing actions only. Extend JSON/text output tests so harvest agents can distinguish actionable prototype work from register/source cascades and already-compatible prototypes.

**Tech Stack:** Python 3.11, `pytest`, Typer CLI, existing `melee-agent` signature audit modules.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/signature_audit.py`: candidate decision helpers, rebucket metadata, source-lever summary behavior.
- Modify `tools/melee-agent/src/cli/debug.py`: text rendering for candidate/rebucket prototype metadata.
- Modify `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`: unit regressions for candidate and rebucket behavior.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: JSON/text CLI regressions for new metadata.
- Keep `docs/superpowers/specs/2026-06-06-signature-prototype-source-lever-ranking-design.md` and this plan staged with the implementation.

## Task 1: Rebucket Non-Executable Static Prototype Audits

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write failing test for same-TU source-register cascade**

Add this test near `test_audit_reports_same_tu_static_helper_prototype_without_patch`:

```python
def test_audit_rebuckets_same_tu_static_source_register_mismatch() -> None:
    source = """
static void helper(int* first, int* second) {}

void caller_fn(int* first, int* second)
{
    helper(first, second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ addi r3, r30, 0",
                "/* 0004 */ addi r4, r31, 0",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ addi r3, r29, 0",
                "/* 0004 */ addi r4, r30, 0",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "register-source-cascade"
    assert action.rebucket["subcategory"] == "argument-source-register"
    assert report.summary["source_lever_action_count"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_same_tu_static_source_register_mismatch -q --no-cov
```

Expected: FAIL because the current code emits `same-tu-static-prototype-audit`.

- [ ] **Step 3: Implement minimal rebucket behavior**

In `_actions_for_finding`, change the static prototype audit fallback so it only
fires when `kind` is not `argument-source-register-mismatch`. Source-register
mismatches should fall through to the generic `call-argument-type-audit`
rebucket:

```python
if (
    candidate_action is None
    and prototype is not None
    and prototype.is_static
    and kind != "argument-source-register-mismatch"
):
    actions.append(
        SignatureAction(
            kind="same-tu-static-prototype-audit",
            confidence="medium",
            affected_call_sites=affected,
            reason=(
                "Call target has a same-translation-unit static "
                "prototype/definition; audit its parameter type against "
                "the expected ABI prep."
            ),
        )
    )
```

- [ ] **Step 4: Run test and verify GREEN**

Run the same single-test command. Expected: PASS.

## Task 2: Add Prototype Decision Metadata and Rebucket Helpers

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write failing tests for register-presence decisions**

Add these tests near the existing global/same-TU prototype candidate tests:

```python
def test_audit_rebuckets_presence_when_global_prototype_bank_already_matches() -> None:
    source = """
void helper(void* obj);

void caller_fn(void* obj)
{
    helper(obj);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ bl helper"],
            ["/* 0000 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "prototype-already-matches-abi-bank"
    assert action.rebucket["subcategory"] == "argument-presence"
    assert action.rebucket["prototype_context"] == {
        "call_target": "helper",
        "arg_index": 0,
        "current_type": "void*",
        "proposed_type": None,
        "current_bank": "GPR",
        "expected_bank": "GPR",
        "expected_register": "r3",
        "current_register": "r3",
        "prototype_scope": "visible-nonstatic",
        "candidate_source": "register-presence-bank",
        "decision_reason": "visible prototype already matches expected ABI bank",
    }
    assert report.summary["source_lever_action_count"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"


def test_audit_rebuckets_presence_when_global_prototype_bank_differs() -> None:
    source = """
void helper(float value);

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ bl helper"],
            ["/* 0000 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "prototype-candidate-unsupported"
    assert action.rebucket["prototype_context"]["current_type"] == "float"
    assert action.rebucket["prototype_context"]["proposed_type"] is None
    assert action.rebucket["prototype_context"]["current_bank"] == "FPR"
    assert action.rebucket["prototype_context"]["expected_bank"] == "GPR"
    assert action.rebucket["prototype_context"]["candidate_source"] == (
        "register-presence-bank"
    )
    assert report.summary["source_lever_action_count"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_presence_when_global_prototype_bank_already_matches \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_presence_when_global_prototype_bank_differs \
  -q --no-cov
```

Expected: FAIL because current code emits prototype candidates with
`proposed_type=None` and no prototype context rebucket.

- [ ] **Step 3: Implement helpers**

Add helper functions below `_types_are_abi_equivalent`:

```python
def _register_abi_bank(register: str | None) -> str | None:
    if register is None:
        return None
    if register.startswith("f"):
        return "FPR"
    if register.startswith("r"):
        return "GPR"
    return None


def _prototype_context(
    *,
    call_target: str,
    arg_index: int,
    current_type: str | None,
    proposed_type: str | None,
    current_bank: str | None,
    expected_bank: str | None,
    expected_register: str | None,
    current_register: str | None,
    prototype_scope: str,
    candidate_source: str,
    decision_reason: str,
) -> dict[str, object]:
    return {
        "call_target": call_target,
        "arg_index": arg_index,
        "current_type": current_type,
        "proposed_type": proposed_type,
        "current_bank": current_bank,
        "expected_bank": expected_bank,
        "expected_register": expected_register,
        "current_register": current_register,
        "prototype_scope": prototype_scope,
        "candidate_source": candidate_source,
        "decision_reason": decision_reason,
    }
```

Update `_rebucket` to accept optional extra fields:

```python
def _rebucket(
    reason: str,
    work_bucket: str,
    subcategory: str,
    explanation: str,
    **extra: object,
) -> dict[str, object]:
    payload = {
        "reason": reason,
        "work_bucket": work_bucket,
        "subcategory": subcategory,
        "explanation": explanation,
    }
    payload.update(extra)
    return payload
```

Add:

```python
def _prototype_already_matches_rebucket(context: dict[str, object]) -> dict[str, object]:
    return _rebucket(
        "prototype-already-matches-abi-bank",
        "signature-call-type",
        "argument-presence",
        (
            "The localized visible prototype already uses the ABI bank implied "
            "by the expected register, so there is no bounded prototype type edit."
        ),
        prototype_context=context,
    )


def _prototype_candidate_unsupported_rebucket(
    context: dict[str, object],
) -> dict[str, object]:
    return _rebucket(
        "prototype-candidate-unsupported",
        "signature-call-type",
        "argument-presence",
        (
            "The localized visible prototype differs from the expected ABI bank, "
            "but register-presence evidence alone is not enough to propose a "
            "safe concrete parameter type or source transform."
        ),
        prototype_context=context,
    )
```

- [ ] **Step 4: Update `_prototype_candidate_action` decision logic**

Extend `_ArgPrepComparison` data flow into action construction:

```python
actions = _actions_for_finding(
    kind=kind,
    expected=expected,
    current=current,
    expected_register=comparison.expected_register,
    current_register=comparison.current_register,
    call=current_call,
    source_context=source_context,
    source_site=source_site,
    arg_index=arg_index,
)
```

Add `expected_register: str | None` and `current_register: str | None` keyword
parameters to `_actions_for_finding` and `_prototype_candidate_action`.

Inside `_prototype_candidate_action`, branch on
`argument-register-presence-mismatch` before calling `_candidate_type_for_prep`.
Presence mismatches must never infer scalar types from `_ArgPrep` alone; they use
register-bank context only and return a rebucket action:

```python
if kind == "argument-register-presence-mismatch":
    expected_bank = _register_abi_bank(expected_register)
    current_bank = _type_abi_bank(current_type) if current_type is not None else None
    candidate_source = "register-presence-bank"
    context = _prototype_context(
        call_target=call.call_target,
        arg_index=arg_index,
        current_type=current_type,
        proposed_type=None,
        current_bank=current_bank,
        expected_bank=expected_bank,
        expected_register=expected_register,
        current_register=current_register,
        prototype_scope=prototype.source_scope,
        candidate_source=candidate_source,
        decision_reason=(
            "visible prototype already matches expected ABI bank"
            if current_bank == expected_bank
            else "register-presence evidence is insufficient for a safe type edit"
        ),
    )
    if current_bank == expected_bank:
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="low",
            affected_call_sites=affected,
            reason="Visible prototype already matches the expected ABI bank.",
            rebucket=_prototype_already_matches_rebucket(context),
        )
    return SignatureAction(
        kind="call-argument-type-audit",
        confidence="low",
        affected_call_sites=affected,
        reason=(
            "Visible prototype bank differs from the expected register bank, "
            "but register-presence evidence alone is not a safe type proposal."
        ),
        rebucket=_prototype_candidate_unsupported_rebucket(context),
    )
```

After the presence branch, handle prep-width candidates:

```python
candidate_source = "prep-width"
proposed_type = _candidate_type_for_prep(expected)
expected_bank = expected.bank if expected is not None else None
current_bank = _type_abi_bank(current_type) if current_type is not None else None
if proposed_type is None:
    context = _prototype_context(
        call_target=call.call_target,
        arg_index=arg_index,
        current_type=current_type,
        proposed_type=None,
        current_bank=current_bank,
        expected_bank=expected_bank,
        expected_register=expected_register,
        current_register=current_register,
        prototype_scope=prototype.source_scope,
        candidate_source=candidate_source,
        decision_reason="prep evidence is insufficient for a safe type edit",
    )
    return SignatureAction(
        kind="call-argument-type-audit",
        confidence="low",
        affected_call_sites=affected,
        reason=(
            "The expected argument prep does not map to a safe concrete "
            "prototype type."
        ),
        rebucket=_prototype_candidate_unsupported_rebucket(context),
    )
```

For prep-width candidates that produce `proposed_type`, add the new metadata
keys to `candidate`: `expected_bank`, `current_bank`, `expected_register`,
`current_register`, `candidate_source`, and `decision_reason`.

- [ ] **Step 5: Run tests and verify GREEN**

Run the two-test command again. Expected: PASS.

## Task 3: Existing Null-Candidate Regressions and CLI Metadata

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/src/cli/debug.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`
- Test: `tools/melee-agent/tests/test_debug_cli_reorg.py`

- [ ] **Step 1: Update existing null-candidate regressions**

Change `test_audit_presence_mismatch_does_not_patch_gpr_alias_type` so it
expects a rebucket instead of a `same-tu-static-prototype-candidate`:

```python
action = finding.actions[0]
assert action.kind == "call-argument-type-audit"
assert action.patch is None
assert action.rebucket["reason"] == "prototype-already-matches-abi-bank"
assert action.rebucket["prototype_context"]["current_type"] == "int"
assert action.rebucket["prototype_context"]["proposed_type"] is None
assert action.rebucket["prototype_context"]["current_bank"] == "GPR"
assert action.rebucket["prototype_context"]["expected_bank"] == "GPR"
assert action.rebucket["prototype_context"]["expected_register"] == "r4"
assert action.rebucket["prototype_context"]["current_register"] is None
```

Change `test_audit_clrlwi_width_candidate_is_unsupported_not_signed_patch` so a
prep with unsupported type inference is rebucketed:

```python
action = report.findings[0].actions[0]
assert action.kind == "call-argument-type-audit"
assert action.patch is None
assert action.rebucket["reason"] == "prototype-candidate-unsupported"
assert action.rebucket["prototype_context"]["current_type"] == "int"
assert action.rebucket["prototype_context"]["proposed_type"] is None
assert action.rebucket["prototype_context"]["candidate_source"] == "prep-width"
```

Add a same-TU FPR/GPR register-presence mismatch test that asserts unsupported
rebucket instead of patch generation:

```python
def test_audit_rebuckets_same_tu_presence_bank_difference_without_type_evidence() -> None:
    source = """
static void helper(float value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ bl helper"],
            ["/* 0000 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

action = report.findings[0].actions[0]
assert action.kind == "call-argument-type-audit"
assert action.rebucket["reason"] == "prototype-candidate-unsupported"
assert action.rebucket["prototype_context"]["current_bank"] == "FPR"
assert action.rebucket["prototype_context"]["expected_bank"] == "GPR"
assert report.summary["source_lever_action_count"] == 0
assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"
```

- [ ] **Step 2: Add CLI output regressions**

In `test_debug_cli_reorg.py`, extend the existing prototype candidate JSON/text
tests to assert:

```python
assert action["candidate"]["expected_bank"] == "GPR"
assert action["candidate"]["current_bank"] == "GPR"
assert action["candidate"]["candidate_source"] == "prep-width"
assert "decision_reason" in action["candidate"]
```

Add a JSON test for rebucket prototype context using a saved checkdiff payload
with `target_asm/current_asm` both `["/* 0000 */ bl helper"]` and source
`void helper(void* obj); void caller_fn(void* obj) { helper(obj); }`. Assert
that `action["rebucket"]["prototype_context"]["current_type"] == "void*"`.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_same_tu_presence_bank_difference_without_type_evidence \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_includes_prototype_candidate \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_candidate_summary \
  -q --no-cov
```

Expected: FAIL before implementation is complete.

- [ ] **Step 4: Implement CLI text metadata**

In `_print_signature_report`, after the current candidate summary, print the
source and banks when present:

```python
if candidate.get("candidate_source") or candidate.get("expected_bank"):
    print(
        "      "
        f"source={candidate.get('candidate_source') or '?'}, "
        f"expected_bank={candidate.get('expected_bank') or '?'}, "
        f"current_bank={candidate.get('current_bank') or '?'}"
    )
```

For rebuckets, if nested `prototype_context` exists, print one compact line:

```python
context = action.rebucket.get("prototype_context")
if isinstance(context, dict):
    print(
        "      prototype: "
        f"{context.get('current_type') or '?'} -> "
        f"{context.get('proposed_type') or 'no-change'} "
        f"({context.get('current_bank') or '?'} -> "
        f"{context.get('expected_bank') or '?'})"
    )
```

- [ ] **Step 5: Run tests and verify GREEN**

Run the command from step 3 plus the new CLI rebucket-context test. Expected:
PASS.

## Task 4: Focused Verification and Live Smokes

**Files:**
- No new code expected.

- [ ] **Step 1: Run focused test suites**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_includes_prototype_candidate \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_candidate_summary \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_summary_and_rebucket \
  -q --no-cov
```

Expected: all selected tests pass.

- [ ] **Step 2: Run syntax and diff checks**

Run:

```bash
/opt/homebrew/bin/python3.11 -m py_compile \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run command-level smokes**

Run:

```bash
melee-agent debug suggest signatures -f it_802A7384 --json > /tmp/issue435-it-after.json
melee-agent debug suggest signatures -f pl_80038144 --json > /tmp/issue435-pl-after.json
/opt/homebrew/bin/python3.11 - <<'PY'
import json
from pathlib import Path
for label in ("it", "pl"):
    payload = json.loads(Path(f"/tmp/issue435-{label}-after.json").read_text())
    print(label, payload["summary"]["stop_condition"])
    print(label, payload["summary"]["action_kind_counts"])
    print(label, payload["summary"]["rebucket_reason_counts"])
PY
```

Expected: `it_802A7384` and `pl_80038144` should no longer use
`source-lever-audit` for null/patchless prototype diagnostics. If a real
candidate remains, it must include `proposed_type` and candidate metadata.

- [ ] **Step 4: Refresh editable install and verify import path**

Run:

```bash
/opt/homebrew/bin/python3.11 -m pip install -e tools/melee-agent
/opt/homebrew/bin/python3.11 - <<'PY'
import src.cli.debug as debug
import src.mwcc_debug.signature_audit as signature_audit
print(debug.__file__)
print(signature_audit.__file__)
PY
```

Expected: both imports point into `/Users/mike/code/melee/tools/melee-agent/src`.

- [ ] **Step 5: Commit and resolve issue**

Stage only the tooling/spec/plan files, not unrelated C source edits:

```bash
git add docs/superpowers/specs/2026-06-06-signature-prototype-source-lever-ranking-design.md
git add docs/superpowers/plans/2026-06-06-signature-prototype-source-lever-ranking.md
git add -f tools/melee-agent/src/mwcc_debug/signature_audit.py
git add -f tools/melee-agent/src/cli/debug.py
git add -f tools/melee-agent/tests/test_mwcc_debug_signature_audit.py
git add -f tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "fix(melee-agent): rebucket non-executable signature prototype audits"
```

After commit, resolve #435 with a note naming the commit and verified behavior.
