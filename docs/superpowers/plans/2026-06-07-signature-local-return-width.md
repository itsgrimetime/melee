# Signature Local Return-Width Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Teach `debug suggest signatures` to detect helper return-width mismatches, emit bounded source variants, and validate those variants against primary and sibling functions.

**Architecture:** Extend the existing signature audit action model with a `SourceVariant` for ordered multi-edit source experiments. Add post-call return-use parsing to `_AsmCall`, generate conservative local return-width variants from localized helper calls, then extend CLI validation to compile once and score primary plus siblings from the same temporary object.

**Tech Stack:** Python dataclasses, Typer CLI, pytest, existing `tools/checkdiff.py` and `debug dump local` temp-object validation.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/signature_audit.py`: source variant dataclass, ordered patch application, return-use parsing, helper-return-width findings, local variant generation, summary counts, validation metadata.
- Modify `tools/melee-agent/src/cli/debug.py`: sibling CLI option, multi-function candidate checkdiff runner, text output for source variants.
- Modify `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`: red/green unit coverage for return-use detection, source variants, patch application, and sibling validation payloads.
- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: CLI JSON/text coverage and multi-function validation runner coverage.
- Use `docs/superpowers/specs/2026-06-07-signature-local-return-width-design.md` as the controlling spec.

## Task 1: SourceVariant Plumbing

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] **Step 1: Write failing tests**

Append tests that define the desired `SourceVariant` API before production changes:

```python
def test_source_variant_applies_ordered_patches_atomically() -> None:
    from src.mwcc_debug.signature_audit import (
        PatchDescriptor,
        SourceVariant,
        _apply_source_variant,
    )

    source = "int value;\\nvalue = helper();\\nuse(value);\\n"
    variant = SourceVariant(
        variant_id="test-variant",
        label="local-temp-widen-consumer-cast",
        patches=[
            PatchDescriptor(None, 1, "int value;", "long value;"),
            PatchDescriptor(None, 3, "use(value);", "use((u8) value);"),
        ],
        candidate={
            "kind": "call-site-local-return-width",
            "helper": "helper",
        },
    )

    patched, error = _apply_source_variant(source, variant)

    assert error is None
    assert patched == "long value;\\nvalue = helper();\\nuse((u8) value);\\n"


def test_source_variant_reports_ambiguous_patch_without_partial_output() -> None:
    from src.mwcc_debug.signature_audit import (
        PatchDescriptor,
        SourceVariant,
        _apply_source_variant,
    )

    source = "value = helper();\\nvalue = helper();\\n"
    variant = SourceVariant(
        variant_id="ambiguous",
        label="raw-helper-call",
        patches=[PatchDescriptor(None, 0, "value = helper();", "value = raw();")],
        candidate={"kind": "call-site-local-return-width"},
    )

    patched, error = _apply_source_variant(source, variant)

    assert patched is None
    assert error == "patch 1 failed: patch text was ambiguous (2 occurrences): 'value = helper();'"
```

- [x] **Step 2: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'source_variant'
```

Expected: both new tests fail because `SourceVariant` and `_apply_source_variant` do not exist.

- [x] **Step 3: Implement source variant primitives**

In `signature_audit.py` add:

```python
@dataclass
class SourceVariant:
    variant_id: str
    label: str
    patches: list[PatchDescriptor]
    candidate: dict[str, object]
```

Extend `SignatureAction` with:

```python
source_variant: SourceVariant | None = None
```

Add ordered application:

```python
def _apply_source_variant(
    source_text: str,
    variant: SourceVariant,
) -> tuple[str | None, str | None]:
    patched = source_text
    for idx, patch in enumerate(variant.patches, start=1):
        patched, error = _apply_patch_descriptor(patched, patch)
        if error is not None:
            return None, f"patch {idx} failed: {error}"
    return patched, None
```

Update `_summarize_report`, `_merge_actions`, and `_action_merge_key` so actions with `source_variant` are counted, merged by `(action.kind, variant_id)`, and do not become unclassified audit-only actions. Add summary keys:

```python
"source_variant_candidate_count"
"local_return_width_candidate_count"
"retained_local_return_width_candidate_count"
```

- [x] **Step 4: Run green tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'source_variant'
```

Expected: new source variant tests pass.

## Task 2: Return-Use Detection

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] **Step 1: Write failing tests**

Add synthetic audit tests:

```python
def test_audit_reports_helper_return_width_mismatch_after_call() -> None:
    source = '''
u8 helper(int idx);

void caller_fn(int idx)
{
    value = helper(idx);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ mr r30, r3",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ clrlwi r30, r3, 24",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    finding = report.findings[0]
    assert finding.kind == "helper-return-width-mismatch"
    assert finding.call_target == "helper"
    assert finding.expected["return_use"]["shape"] == "plain-move"
    assert finding.current["return_use"]["shape"] == "zero-extend-8"
    assert finding.actions[0].kind == "call-site-local-return-width"


def test_audit_follows_one_hop_return_copy_to_mask() -> None:
    source = '''
u8 helper(int idx);

void caller_fn(int idx)
{
    value = helper(idx);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ bl helper",
                "/* 0004 */ mr r29, r3",
                "/* 0008 */ mr r30, r29",
            ],
            [
                "/* 0000 */ bl helper",
                "/* 0004 */ mr r29, r3",
                "/* 0008 */ rlwinm r30, r29, 0, 24, 31",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    finding = report.findings[0]
    assert finding.kind == "helper-return-width-mismatch"
    assert finding.current["return_use"]["shape"] == "zero-extend-8"
    assert finding.current["return_use"]["through_copy"] is True
```

- [x] **Step 2: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'helper_return_width or one_hop_return'
```

Expected: tests fail because return-use analysis is absent.

- [x] **Step 3: Implement return-use parsing**

Add `_ReturnUse` dataclass:

```python
@dataclass(frozen=True)
class _ReturnUse:
    register: str
    source_register: str
    shape: str
    width: int | None
    opcode: str
    text: str
    through_copy: bool
```

Extend `_AsmCall` with:

```python
return_use: _ReturnUse | None = None
```

Update `_parse_asm_calls` to call `_collect_return_use(instrs, instr_index, window)`.

Implement `_collect_return_use` by scanning after the call, stopping at branch/call boundaries, tracking `r3` plus one copied register, and recognizing:

- `mr dst,r3` or `mr dst,copy` as `plain-move`, width 32;
- `clrlwi dst,src,24` as `zero-extend-8`;
- `clrlwi dst,src,16` as `zero-extend-16`;
- `rlwinm dst,src,0,24,31` as `zero-extend-8`;
- `rlwinm dst,src,0,16,31` as `zero-extend-16`;
- `extsb dst,src` as `sign-extend-8`;
- `extsh dst,src` as `sign-extend-16`.

When a narrowing use is found after a one-hop copy, prefer it over the earlier plain copy. If no narrowing is found, return the first plain move.

- [x] **Step 4: Implement return-width findings**

Add `_return_width_findings(target_calls, current_calls, source_context)` and include its output in `audit_signature_call_type` before `_call_prep_findings`.

Generate a finding when `_return_use_width(expected) != _return_use_width(current)` or one side is `plain-move` and the other is a narrow shape. Use `_source_site_for_call` and require target-ordinal localization for source variants.

- [x] **Step 5: Run green tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'helper_return_width or one_hop_return'
```

Expected: new return-use tests pass.

## Task 3: Local Return-Width Variant Generation

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] **Step 1: Write failing tests**

Add tests for conservative variants and unsafe cases:

```python
def test_return_width_action_generates_local_temp_widen_variant() -> None:
    source = '''
u8 helper(int idx);
void sink(u8 value);

void caller_fn(int idx)
{
    u8 value;
    value = helper(idx);
    sink(value);
}
'''
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ bl helper", "/* 0004 */ mr r30, r3"],
            ["/* 0000 */ bl helper", "/* 0004 */ clrlwi r30, r3, 24"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.kind == "call-site-local-return-width"
    assert action.source_variant is not None
    assert action.source_variant.label == "local-temp-widen-consumer-cast"
    patched, error = _apply_source_variant(source, action.source_variant)
    assert error is None
    assert "int value;" in patched
    assert "sink((u8) value);" in patched


def test_return_width_action_rejects_overall_ordinal_localization() -> None:
    source = '''
u8 helper_alias(int idx);
u8 helper(int idx);

void caller_fn(int idx)
{
    helper_alias(idx);
}
'''
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ bl helper", "/* 0004 */ mr r30, r3"],
            ["/* 0000 */ bl helper", "/* 0004 */ clrlwi r30, r3, 24"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.source_variant is None
    assert action.rebucket["reason"] == "return-width-source-localization-unsafe"
```

- [x] **Step 2: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'return_width_action'
```

Expected: tests fail until variant generation exists.

- [x] **Step 3: Parse return types and include prototypes**

Extend `_PrototypeInfo` with `return_type: str | None = None`.

Update `_parse_visible_prototypes` to preserve line numbers while stripping C comments, extract a normalized return type from the prefix, and parse included headers from source files. Implement direct include resolution for:

- `#include "local.h"` relative to the source file directory;
- `#include <melee/...>` under `<repo>/src/melee/...`;
- `#include <baselib/...>` under `<repo>/src/sysdolphin/baselib/...`.

Do not recurse includes in this task.

- [x] **Step 4: Support simple function-like macro aliases**

Add `_parse_call_aliases` for macros like:

```c
#define mnDiagram_GetNameByIndex_s(x) ((int) mnDiagram_GetNameByIndex(x))
```

Store alias metadata in `_SourceContext`. When building call sites, index the same source site by both the source call target and the underlying helper target, recording `source_call_target` and `underlying_call_target`.

- [x] **Step 5: Generate variants**

Implement `_return_width_action` so it:

- requires target-ordinal localization;
- uses the underlying helper target for prototype lookup;
- requires a narrow helper return type or an underlying helper with a known narrow prototype;
- identifies a simple assignment receiver from the source line;
- if the receiver local type is narrow, emits `local-temp-widen-consumer-cast` with declaration and direct consumer patches;
- if the receiver local type is already `int` and the source call is an alias macro, emits `raw-helper-call` replacing the alias call with the underlying helper call;
- otherwise emits a rebucket `return-width-source-shape-unsupported`.

- [x] **Step 6: Run green tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  -q -k 'return_width_action or helper_return_width or one_hop_return or source_variant'
```

Expected: all targeted signature audit tests pass.

## Task 4: Validation and CLI Output

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/src/cli/debug.py`
- Test: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`
- Test: `tools/melee-agent/tests/test_debug_cli_reorg.py`

- [x] **Step 1: Write failing validation tests**

Add a unit test to `test_mwcc_debug_signature_audit.py`:

```python
def test_validate_source_variant_rejects_sibling_regression() -> None:
    from src.mwcc_debug.signature_audit import (
        PatchDescriptor,
        SignatureAction,
        SignatureAuditReport,
        SignatureFinding,
        SourceVariant,
        validate_signature_patches,
    )

    action = SignatureAction(
        kind="call-site-local-return-width",
        confidence="medium",
        affected_call_sites=[],
        reason="test",
        source_variant=SourceVariant(
            variant_id="v1",
            label="local-temp-widen-consumer-cast",
            patches=[PatchDescriptor(None, 1, "u8 value;", "int value;")],
            candidate={"kind": "call-site-local-return-width"},
        ),
    )
    report = SignatureAuditReport(
        function="caller_fn",
        classification=None,
        findings=[
            SignatureFinding(
                kind="helper-return-width-mismatch",
                confidence="medium",
                call_target="helper",
                call_ordinal=1,
                arg_register=None,
                expected={},
                current={},
                source_line=1,
                arg_index=None,
                affected_call_sites=[],
                actions=[action],
            )
        ],
    )

    def fake_runner(candidate_source: str, functions: list[str]) -> dict[str, dict]:
        assert functions == ["caller_fn", "sibling_fn"]
        return {
            "caller_fn": {"match": False, "fuzzy_match_percent": 99.0},
            "sibling_fn": {"match": False, "fuzzy_match_percent": 94.0},
        }

    validate_signature_patches(
        report,
        "u8 value;\\n",
        lambda candidate_source: {"match": False},
        baseline_match_percent=97.5,
        primary_function="caller_fn",
        sibling_functions=["sibling_fn"],
        sibling_baseline_match_percent={"sibling_fn": 95.0},
        run_candidate_multi=fake_runner,
    )

    validation = action.validation
    assert validation["retained"] is False
    assert validation["rejection_reason"] == "sibling-regressed"
    assert validation["primary"]["delta_match_percent"] == 1.5
    assert validation["siblings"][0]["function"] == "sibling_fn"
    assert validation["siblings"][0]["delta_match_percent"] == -1.0
```

- [x] **Step 2: Write failing CLI tests**

Add CLI tests in `test_debug_cli_reorg.py` for JSON/text output and multi-runner restoration:

```python
def test_debug_suggest_signatures_json_includes_local_return_width_variant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            u8 helper(int idx);

            void caller_fn(int idx)
            {
                u8 value;
                value = helper(idx);
                sink(value);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-return-width"},
            "target_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ mr r30, r3",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ clrlwi r30, r3, 24",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    action = report["findings"][0]["actions"][0]
    assert action["kind"] == "call-site-local-return-width"
    assert action["source_variant"]["label"] == "local-temp-widen-consumer-cast"
    assert action["candidate"]["kind"] == "call-site-local-return-width"
```

Use existing CLI tests in the same file as templates; include complete temp source and JSON payload rather than relying on live repo state.

- [x] **Step 3: Run red tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py \
  -q -k 'source_variant_rejects_sibling_regression or local_return_width_variant'
```

Expected: tests fail until validation and CLI output are implemented.

- [x] **Step 4: Extend validation**

Update `validate_signature_patches` with optional keyword parameters:

```python
primary_function: str | None = None
sibling_functions: list[str] | None = None
sibling_baseline_match_percent: dict[str, float | None] | None = None
run_candidate_multi: Callable[[str, list[str]], dict[str, dict]] | None = None
```

For `source_variant` actions, apply `_apply_source_variant`, call `run_candidate_multi` once when available, and attach nested primary/sibling validation. Retain only when the primary matches or has positive delta and every scored sibling delta is `>= 0`.

- [x] **Step 5: Add multi-function CLI runner**

In `debug.py`, add `_run_signature_candidate_checkdiff_many` by factoring `_run_signature_candidate_checkdiff` so candidate source is compiled once, copied to the build object once under the repo lock, and checked for all requested functions before restoration.

Keep `_run_signature_candidate_checkdiff` as a wrapper that calls the new function with one function.

- [x] **Step 6: Add sibling options and output**

Add repeatable Typer option:

```python
sibling_function: Annotated[
    Optional[list[str]],
    typer.Option(
        "--sibling-function",
        help="Additional sibling function to score against validated source variants.",
    ),
] = None
```

Infer siblings from local return-width candidates when no explicit siblings are provided. For `mnDiagram2_UpdateHeader` or `mnDiagram2_Create`, include `mnDiagram2_GetRankedName` and `mnDiagram2_GetRankedFighter` when they are present in the source file.

Update text output to print `source_variant` details and nested primary/sibling validation.

- [x] **Step 7: Run green tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py \
  -q -k 'signature or local_return_width or source_variant'
```

Expected: targeted tests pass without changing unrelated C files.

## Task 5: Verification, Smoke, Commit, and Issue Resolution

**Files:**
- Modify: `/Users/mike/.codex/automations/issue-resolver-2/memory.md` only if recording final automation memory is needed.
- No production code beyond Tasks 1-4.

- [x] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py \
  -q
```

Expected: both focused test files pass.

- [x] **Step 2: Run compile and diff checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m py_compile \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py
git diff --check -- \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py \
  docs/superpowers/plans/2026-06-07-signature-local-return-width.md
```

Expected: both commands exit 0.

- [x] **Step 3: Run command-level smoke checks**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures \
  -f mnDiagram2_UpdateHeader \
  --source-file src/melee/mn/mndiagram2.c \
  --json > /tmp/sig-update-local-return.json
python - <<'PY'
import json
p=json.load(open('/tmp/sig-update-local-return.json'))
actions=[
    a
    for f in p.get('findings', [])
    for a in f.get('actions', [])
    if a.get('kind') == 'call-site-local-return-width'
]
print(len(actions))
print([a.get('source_variant', {}).get('label') for a in actions])
PY
```

Expected: at least one `call-site-local-return-width` action is printed.

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures \
  -f mnDiagram2_Create \
  --source-file src/melee/mn/mndiagram2.c \
  --json > /tmp/sig-create-local-return.json
python - <<'PY'
import json
p=json.load(open('/tmp/sig-create-local-return.json'))
print(p["summary"]["stop_condition"]["kind"])
print(p["summary"].get("local_return_width_candidate_count"))
PY
```

Expected: stop condition is not generic `rebucketed-audit-only`, or local return-width candidate count is non-zero.

- [x] **Step 4: Commit implementation and resolve issue**

Stage only tooling/spec/plan files:

```bash
git add \
  docs/superpowers/plans/2026-06-07-signature-local-return-width.md \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "Add local return-width signature variants"
commit=$(git rev-parse --short HEAD)
PYTHONPATH=tools/melee-agent python -m src.cli issue resolve 502 \
  --note "fixed in ${commit}: signature suggestions now emit call-site-local return-width source variants with primary/sibling validation"
```

Expected: commit succeeds; issue #502 is resolved.

- [x] **Step 5: Refresh editable install and final queue**

Run:

```bash
python -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/bin/melee-agent issue list --status open
/opt/homebrew/bin/python3 - <<'PY'
import inspect
import src.cli
print(inspect.getfile(src.cli))
PY
git status --short --branch
```

Expected: editable install imports from `/Users/mike/code/melee/tools/melee-agent`; issue queue has no actionable open issues; only unrelated dirty C files remain if the user has not cleaned them.
