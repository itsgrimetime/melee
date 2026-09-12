# Signature Prototype Candidate Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `debug suggest signatures` turn localized argument-width and argument-presence mismatches into bounded prototype candidates or narrower stop reasons instead of generic prototype-candidate-missing rebuckets.

**Architecture:** Extend the signature audit data model with prototype source metadata and structured candidate metadata. Add conservative candidate inference before the generic rebucket fallback, with patch generation only for trusted same-TU static single-declaration parameter type changes. Keep all validation on the existing temporary source/object path.

**Tech Stack:** Python dataclasses, regex-based C source parsing, pytest, Typer CLI tests.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/signature_audit.py`: data model, prototype parsing, candidate inference, safer presence comparison, rebuckets, summary action kinds.
- Modify `tools/melee-agent/src/cli/debug.py`: concise text rendering for `SignatureAction.candidate`.
- Modify `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`: unit coverage for prototype candidates and narrower stop reasons.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: JSON and text CLI candidate output coverage.
- Keep `docs/superpowers/specs/2026-06-05-signature-prototype-candidate-inference-design.md` with this plan in the final commit.

## Task 1: Add Prototype Candidate Unit Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write failing width-candidate tests**

Append tests that exercise these behaviors:

```python
def test_audit_generates_same_tu_static_width_prototype_patch() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    finding = report.findings[0]
    assert finding.kind == "argument-width-mismatch"
    action = finding.actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.candidate["kind"] == "prototype-parameter-type"
    assert action.candidate["current_type"] == "int"
    assert action.candidate["proposed_type"] == "s8"
    assert action.candidate["prototype_scope"] == "same-tu-static"
    assert action.candidate["patch_status"] == "generated"
    assert action.patch is not None
    assert action.patch.old == "int value"
    assert action.patch.new == "s8 value"
    assert report.summary["patch_candidate_count"] == 1
```

```python
def test_validate_signature_prototype_patch_attaches_candidate_delta() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    seen_sources: list[str] = []

    def fake_runner(candidate_source: str) -> dict:
        seen_sources.append(candidate_source)
        return {"match": False, "fuzzy_match_percent": 99.0}

    validate_signature_patches(report, source, fake_runner, baseline_match_percent=97.5)

    assert "static void helper(s8 value) {}" in seen_sources[0]
    assert report.findings[0].actions[0].validation["status"] == "scored"
    assert report.summary["validated_patch_candidate_count"] == 1
```

- [ ] **Step 2: Write failing non-patch candidate tests**

Add tests for:

```python
def test_audit_reports_global_width_prototype_candidate_without_patch() -> None:
    source = """
void helper(int value);

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "global-prototype-candidate"
    assert action.patch is None
    assert action.candidate["blast_radius"] == "cross-translation-unit"
    assert report.summary["source_lever_action_count"] == 1
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "source-lever-audit"
```

```python
def test_audit_reports_duplicate_same_tu_declarations_without_patch() -> None:
    source = """
static void helper(int value);
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.patch is None
    assert action.candidate["patch_status"] == "duplicate-visible-declarations"
```

- [ ] **Step 3: Write failing narrower-rebucket tests**

Add tests for:

```python
def test_audit_rebuckets_width_mismatch_without_visible_prototype() -> None:
    source = """
void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "external-prototype-unavailable"
    assert "width-prototype-candidate-missing" not in report.summary["rebucket_reason_counts"]
```

```python
def test_audit_rebuckets_variadic_presence_mismatch_tail() -> None:
    source = """
void helper(const char *fmt, ...);

void caller_fn(int value)
{
    helper("%d", value);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ mr r4, r30",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "variadic-prototype-tail"
```

```python
def test_audit_rebuckets_surplus_abi_prep_as_source_call_arity_mismatch() -> None:
    source = """
void helper(int first);

void caller_fn(int first, int second)
{
    helper(first);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ mr r4, r30",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-register-presence-mismatch"
    assert report.findings[0].arg_index == 1
    assert report.findings[0].actions[0].rebucket["reason"] == "source-call-arity-mismatch"
```

- [ ] **Step 4: Write failing safety tests**

Add tests for:

```python
def test_audit_overall_ordinal_prototype_candidate_never_patches() -> None:
    source = """
static void source_helper(int value) {}

void caller_fn(int first, int second)
{
    first_helper(first);
    source_helper(second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl first_helper",
                "/* 0008 */ extsb r3, r30",
                "/* 000C */ bl external_helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl first_helper",
                "/* 0008 */ mr r3, r30",
                "/* 000C */ bl external_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.candidate["localization_kind"] == "overall-ordinal"
    assert action.patch is None
```

```python
def test_audit_unsupported_parameter_shape_reports_patch_status() -> None:
    source = """
static void helper(int values[2]) {}

void caller_fn(int *values)
{
    helper(values);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.patch is None
    assert action.candidate["patch_status"] == "unsupported-parameter-shape"
```

- [ ] **Step 5: Run the new unit tests and verify RED**

Run the new test names individually:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_generates_same_tu_static_width_prototype_patch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_validate_signature_prototype_patch_attaches_candidate_delta \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_reports_global_width_prototype_candidate_without_patch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_reports_duplicate_same_tu_declarations_without_patch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_width_mismatch_without_visible_prototype \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_variadic_presence_mismatch_tail \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_rebuckets_surplus_abi_prep_as_source_call_arity_mismatch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_overall_ordinal_prototype_candidate_never_patches \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_unsupported_parameter_shape_reports_patch_status \
  -q --no-cov
```

Expected before implementation: failures due to missing `candidate` field, generic rebuckets, or no surplus comparison.

## Task 2: Implement Candidate Data Model and Prototype Metadata

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`

- [ ] **Step 1: Extend dataclasses**

Add `candidate: dict[str, object] | None = None` to `SignatureAction` after `rebucket`.

Extend `_PrototypeInfo` with:

```python
is_definition: bool = False
line: int | None = None
param_texts: tuple[str, ...] = ()
param_names: tuple[str | None, ...] = ()
declaration_count: int = 1
source_scope: str = "unknown"
```

- [ ] **Step 2: Preserve prototype source metadata**

Update `_parse_visible_prototypes()` to compute:

- `line = source_text[:match.start("name")].count("\n") + 1`
- `is_definition = suffix[0] == "{"`
- `param_texts = tuple(_split_args(params))`, excluding `void` and `...`
- `param_names` from a new helper `_extract_param_name(param_text)`.
- `source_scope = "same-tu-static"` for static prototypes/definitions, otherwise `"visible-nonstatic"`.
- `declaration_count`: increment when the same function name appears more than once.

Keep existing behavior that prefers static information over non-static information, but preserve duplicate static counts.

- [ ] **Step 3: Add helpers for parameter splitting and patchability**

Implement helpers:

```python
def _extract_param_name(param_text: str) -> str | None: ...
def _split_param_type_name(param_text: str) -> tuple[str, str] | None: ...
def _is_simple_scalar_integer_type(type_text: str) -> bool: ...
def _prototype_patch_status(prototype, arg_index, source_site, call) -> str: ...
def _trusted_patch_localization(source_site, call) -> bool: ...
```

Rules:

- reject multiline parameter text;
- reject arrays (`[` or `]`);
- reject function pointers (`"(*"` or nested declarator shape);
- reject duplicate declarations (`declaration_count != 1`);
- reject overall-ordinal localization for patches;
- reject if source call target and resolved ASM call target differ.

- [ ] **Step 4: Run data-model focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_reports_duplicate_same_tu_declarations_without_patch \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py::test_audit_unsupported_parameter_shape_reports_patch_status \
  -q --no-cov
```

Expected after this task: these tests may still fail on candidate inference, but prototype metadata parsing should no longer crash.

## Task 3: Implement Width and Presence Candidate Inference

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`

- [ ] **Step 1: Include surplus ABI preps in localized comparisons**

In `_arg_prep_comparisons()`, when a source site exists, compute `expected_args = _ordered_arg_preps(expected_call)` and `current_args = _ordered_arg_preps(current_call)`. Set:

```python
max_args = max(len(expected_registers), len(current_registers), len(expected_args), len(current_args))
```

When `arg_index` exceeds source-derived register lists, fall back to ordered prep registers. This creates presence findings for surplus ABI args.

- [ ] **Step 2: Add candidate inference before generic fallback**

In `_actions_for_finding()`, after the remove-cast and existing static audit logic, call a helper:

```python
candidate_action = _prototype_candidate_action(
    kind=kind,
    expected=expected,
    current=current,
    call=call,
    source_context=source_context,
    source_site=source_site,
    source_arg=source_arg,
    prototype=prototype,
    affected=affected,
    arg_index=arg_index,
)
if candidate_action is not None:
    actions.append(candidate_action)
```

Avoid adding the old `same-tu-static-prototype-audit` when a concrete prototype candidate action is emitted for the same finding.

- [ ] **Step 3: Implement candidate type inference**

Implement:

```python
def _candidate_type_for_prep(prep: _ArgPrep | None) -> str | None:
    if prep is None or prep.bank != "GPR":
        return None
    if prep.opcode == "extsb" or (prep.width == 8 and prep.load_kind != "integer-load"):
        return "s8"
    if prep.opcode == "lbz":
        return "u8"
    if prep.opcode in {"extsh", "lha"}:
        return "s16"
    if prep.opcode == "lhz":
        return "u16"
    if prep.width == 32 and prep.opcode in {"mr", "lwz", "li", "addi"}:
        return "s32"
    return None
```

Unsupported `clrlwi`/`rlwinm` should return `None` so the action can report `unsupported-type-shape` if there is a prototype but no safe proposed type.

- [ ] **Step 4: Implement candidate and rebucket helpers**

For visible prototypes:

- same-TU static: `kind="same-tu-static-prototype-candidate"`, `confidence="medium"`, `blast_radius="same-translation-unit"`.
- non-static: `kind="global-prototype-candidate"`, `confidence="low"`, `blast_radius="cross-translation-unit"`, no patch.

Candidate dictionary must include:

```python
{
    "kind": "prototype-parameter-type",
    "call_target": call.call_target,
    "arg_index": arg_index,
    "current_type": current_type,
    "proposed_type": proposed_type,
    "prototype_scope": prototype.source_scope,
    "blast_radius": ...,
    "patch_status": ...,
    "localization_kind": source_site.get("localization_kind"),
    "reason": "...",
}
```

For missing/unsafe cases, update `_argument_rebucket()` or introduce a new helper to emit:

- `external-prototype-unavailable` for localized width/presence findings with no visible prototype.
- `variadic-prototype-tail` when `prototype.is_variadic and arg_index >= len(prototype.param_types)`.
- `source-call-arity-mismatch` when `source_arg is None` for a localized source call.

- [ ] **Step 5: Add source-lever action kinds**

Add these to `SOURCE_LEVER_ACTION_KINDS`:

```python
"same-tu-static-prototype-candidate",
"global-prototype-candidate",
```

- [ ] **Step 6: Run unit tests and verify GREEN**

Run the Task 1 test command again. Expected: all new unit tests pass.

## Task 4: Add CLI Candidate Output Tests and Formatter

**Files:**
- Modify: `tools/melee-agent/tests/test_debug_cli_reorg.py`
- Modify: `tools/melee-agent/src/cli/debug.py`

- [ ] **Step 1: Add failing JSON CLI regression**

Add a test near existing `debug suggest signatures` tests that writes a static helper fixture and checkdiff payload, invokes:

```bash
debug suggest signatures -f caller_fn --checkdiff-json <payload> --json
```

Assert:

```python
action = report["findings"][0]["actions"][0]
assert action["kind"] == "same-tu-static-prototype-candidate"
assert action["candidate"]["proposed_type"] == "s8"
assert action["patch"]["old"] == "int value"
```

- [ ] **Step 2: Add failing text CLI regression**

Invoke the same fixture without `--json` and assert output contains:

```text
candidate: prototype-parameter-type int -> s8 (same-translation-unit, generated)
```

- [ ] **Step 3: Implement text formatting**

In `_print_signature_report()`, after patch output and before rebucket output, add:

```python
candidate = getattr(action, "candidate", None)
if candidate:
    print(
        "    candidate: "
        f"{candidate.get('kind')} "
        f"{candidate.get('current_type') or '?'} -> "
        f"{candidate.get('proposed_type') or '?'} "
        f"({candidate.get('blast_radius') or '?'}, "
        f"{candidate.get('patch_status') or 'diagnostic'})"
    )
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_includes_prototype_candidate \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_candidate_summary \
  -q --no-cov
```

Expected: both pass after formatter implementation.

## Task 5: Focused Verification and Smoke

**Files:**
- No new files beyond listed implementation/test files.

- [ ] **Step 1: Run focused signature tests**

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_includes_candidate \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_summary_and_rebucket \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_candidate_summary \
  -q --no-cov
```

If the worker names the JSON CLI test differently, run that exact new test name instead of `test_debug_suggest_signatures_json_includes_candidate`.

- [ ] **Step 2: Compile changed modules**

```bash
/opt/homebrew/bin/python3.11 -m py_compile \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py
```

- [ ] **Step 3: Command-level help smoke**

```bash
PYTHONPATH=tools/melee-agent /opt/homebrew/bin/python3.11 -m src.cli debug suggest signatures --help
```

- [ ] **Step 4: Live sample smoke**

Run:

```bash
melee-agent debug suggest signatures -f fn_8019F9C4 --json
```

Confirm that:

- the JSON parses;
- `summary.rebucket_reason_counts` does not contain `call-not-localized`;
- localized argument-width/presence findings now contain either `candidate` metadata or narrower reasons such as `external-prototype-unavailable`, `variadic-prototype-tail`, or `source-call-arity-mismatch`.

- [ ] **Step 5: Review diff**

Run:

```bash
git diff -- tools/melee-agent/src/mwcc_debug/signature_audit.py tools/melee-agent/src/cli/debug.py tools/melee-agent/tests/test_mwcc_debug_signature_audit.py tools/melee-agent/tests/test_debug_cli_reorg.py docs/superpowers/specs/2026-06-05-signature-prototype-candidate-inference-design.md docs/superpowers/plans/2026-06-05-signature-prototype-candidate-inference.md
git diff --check
```

Expected: no unrelated files in the signature diff and no whitespace errors.
