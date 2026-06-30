# Signature Call-Type Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `debug suggest signatures` diagnostic that turns checkdiff call-prep signature/type mismatches into ranked source-level candidate actions.

**Architecture:** Implement the parsing and ranking logic in a new focused `src/mwcc_debug/signature_audit.py` module. Wire it into `src/cli/debug.py` as a read-only `debug suggest signatures` command with optional saved checkdiff JSON input and optional validation for one-line cast-removal descriptors.

**Tech Stack:** Python dataclasses, Typer CLI, existing `cast_audit.find_call_sites`, existing `source_patch.find_function`, pytest with synthetic checkdiff JSON fixtures.

---

### Task 1: Core Signature Audit Model

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Create: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write parser and ranking regression tests**

Create `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py` with tests that import:

```python
from src.mwcc_debug.signature_audit import audit_signature_call_type
```

Add a helper payload:

```python
def _payload(target_asm: list[str], current_asm: list[str]) -> dict:
    return {
        "function": "caller_fn",
        "classification": {"primary": "signature-type-mismatch"},
        "target_asm": target_asm,
        "current_asm": current_asm,
        "diff": [],
        "fuzzy_match_percent": 97.5,
    }
```

Add `test_audit_suggests_removing_explicit_float_cast_for_gpr_target`:

```python
def test_audit_suggests_removing_explicit_float_cast_for_gpr_target() -> None:
    source = '''
void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tfmr f1, f31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-bank-mismatch"
    action = report.findings[0].actions[0]
    assert action.kind == "remove-call-arg-cast"
    assert action.confidence == "high"
    assert action.patch is not None
    assert action.patch.old == "(f32) rumble_setting"
    assert action.patch.new == "rumble_setting"
```

This test intentionally omits a visible prototype for `helper`. The candidate
is high-confidence only because the call is default-promotion sensitive.

Add `test_audit_does_not_patch_fixed_prototype_cast`:

```python
def test_audit_does_not_patch_fixed_prototype_cast() -> None:
    source = '''
static void helper(int value) {}

void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tfmr f1, f31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-bank-mismatch"
    assert all(a.patch is None for a in report.findings[0].actions)
    assert any(a.kind == "same-tu-static-prototype-audit" for a in report.findings[0].actions)
```

Add `test_audit_does_not_patch_unknown_or_float_inner_expression`:

```python
def test_audit_does_not_patch_unknown_or_float_inner_expression() -> None:
    unknown_source = '''
void caller_fn(void)
{
    helper((f32) unknown_expr);
}
'''
    unknown = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tfmr f1, f31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        unknown_source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert all(a.patch is None for a in unknown.findings[0].actions)

    float_source = '''
void caller_fn(float value)
{
    helper((f32) value);
}
'''
    declared_float = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tfmr f1, f31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        float_source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert all(a.patch is None for a in declared_float.findings[0].actions)
```

Add `test_audit_reports_same_tu_static_helper_prototype_without_patch`:

```python
def test_audit_reports_same_tu_static_helper_prototype_without_patch() -> None:
    source = '''
static void helper(float value) {}

void caller_fn(int arg0)
{
    helper(arg0);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tfmr f1, f31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    actions = report.findings[0].actions
    assert any(a.kind == "same-tu-static-prototype-audit" for a in actions)
    assert all(a.patch is None for a in actions)
```

Add `test_audit_classifies_width_mismatch`:

```python
def test_audit_classifies_width_mismatch() -> None:
    source = '''
void caller_fn(u8 arg0)
{
    helper(arg0);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\textsb r3, r31",
                "/* 0004 */\\tbl helper",
            ],
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-width-mismatch"
    assert report.findings[0].actions[0].kind == "call-argument-type-audit"
```

Add `test_audit_reports_unmatched_call_target_shape`:

```python
def test_audit_reports_unmatched_call_target_shape() -> None:
    source = '''
void caller_fn(int arg0)
{
    helper_b(arg0);
}
'''
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper_a",
            ],
            [
                "/* 0000 */\\tmr r3, r31",
                "/* 0004 */\\tbl helper_b",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "call-target-shape-mismatch"
    assert report.findings[0].expected["call_target"] == "helper_a"
    assert report.findings[0].current["call_target"] == "helper_b"
    assert report.findings[0].affected_call_sites[0]["call_target"] == "helper_b"
    assert report.findings[0].actions[0].kind == "call-target-shape-audit"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/mike/code/melee
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_mwcc_debug_signature_audit.py -q
```

Expected: import failure for `src.mwcc_debug.signature_audit`.

- [ ] **Step 3: Implement the module**

Implement:

```python
@dataclass(frozen=True)
class PatchDescriptor:
    source_file: str | None
    line: int
    old: str
    new: str

@dataclass
class SignatureAction:
    kind: str
    confidence: str
    affected_call_sites: list[dict]
    reason: str
    patch: PatchDescriptor | None = None
    validation: dict | None = None

@dataclass
class SignatureFinding:
    kind: str
    confidence: str
    call_target: str | None
    call_ordinal: int
    arg_register: str | None
    expected: dict
    current: dict
    source_line: int | None
    arg_index: int | None
    affected_call_sites: list[dict]
    actions: list[SignatureAction]

@dataclass
class SignatureAuditReport:
    function: str
    classification: str | None
    findings: list[SignatureFinding]
```

Implement `audit_signature_call_type(checkdiff_payload, source_text, function, source_file=None, window=10)`.

Parser requirements:

- Strip optional checkdiff comments before opcodes.
- Recognize `bl <symbol>`.
- Recognize final writes to ABI argument registers:
  GPR `r3-r10`, FPR `f1-f13`.
- Treat `mr`, `li`, `addi`, `lwz`, `lbz`, `lhz`, `lha`, `extsb`, `extsh`,
  `clrlwi`, `rlwinm` as GPR prep.
- Treat `fmr`, `lfs`, `lfd`, and simple FP arithmetic with destination `fN`
  as FPR prep.
- Pair calls by `(call_target, ordinal among calls to that target)`.
- Also align calls by overall call ordinal and emit `call-target-shape-mismatch`
  when the targets differ or one side is missing.
- Match source calls by the same target ordinal using `find_call_sites`.
- Parse visible prototypes/function definitions into a lightweight record:
  `has_prototype`, `is_static`, `is_variadic`, and `param_types`.

Ranking requirements:

- GPR-vs-FPR differences produce `argument-bank-mismatch`.
- Width-shaping opcode differences produce `argument-width-mismatch`.
- Integer-load-vs-float-load differences produce `argument-load-kind-mismatch`.
- Same register bank but different source register produces
  `argument-source-register-mismatch`.
- If the source argument begins with an explicit cast, the expected bank
  disagrees with that cast, and prototype evidence says the call is
  default-promotion sensitive (no visible prototype or a variadic argument
  beyond fixed params), emit a high-confidence `remove-call-arg-cast` action
  with a `PatchDescriptor`.
- Require positive evidence that the inner expression type matches the expected
  ABI bank before emitting that patch. For example, `(f32) rumble_setting` may
  get a GPR remove-cast patch only when `rumble_setting` is declared integer or
  matches a conservative integer heuristic. Unknown expressions and declared
  float expressions are audit-only.
- If the source argument begins with an explicit cast but a fixed prototype
  controls ABI passing, do not emit a patch; emit a prototype/type audit action.
- If the call target has a same-file `static` definition, emit
  `same-tu-static-prototype-audit`.
- Aggregate actions by root cause key `(kind, call_target, arg_index, action
  kind)` and list affected call sites, so repeated calls to the same helper do
  not appear as unrelated work.
- Always emit at least one source-audit action for a finding, even when no
  patch is safe.

- [ ] **Step 4: Run module tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_mwcc_debug_signature_audit.py -q
```

Expected: all tests pass.

### Task 2: CLI Command And Validation

**Files:**
- Modify: `tools/melee-agent/src/cli/debug.py`
- Modify: `tools/melee-agent/tests/test_debug_cli_reorg.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [ ] **Step 1: Write CLI and validation tests**

In `tools/melee-agent/tests/test_debug_cli_reorg.py`, add a test that:

- creates a temporary source file under `tmp_path/src/melee/test/test.c`;
- monkeypatches `debug_cli.DEFAULT_MELEE_ROOT` to `tmp_path`;
- monkeypatches `_find_unit_for_function` to return `melee/test/test`;
- writes a saved checkdiff JSON file;
- invokes:

```python
result = runner.invoke(
    app,
    [
        "debug", "suggest", "signatures",
        "-f", "caller_fn",
        "--checkdiff-json", str(payload_path),
        "--json",
    ],
)
```

Assert `result.exit_code == 0`, parse stdout as JSON, and assert:

```python
payload["function"] == "caller_fn"
payload["findings"][0]["kind"] == "argument-bank-mismatch"
payload["findings"][0]["actions"][0]["kind"] == "remove-call-arg-cast"
```

In `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`, add a
validation test for `validate_signature_patches` using a monkeypatched runner
callable. It should pass `source_path` and `source_text`, assert the real source
file bytes are unchanged after validation, assert the runner received patched
source text, and assert the candidate action receives
`validation.status == "improved"` when the runner returns a higher match
percent.

Also add a focused test for the CLI candidate runner helper by monkeypatching
`subprocess.run`, `_acquire_checkdiff_repo_lock`, and the build object path
resolver. The test should assert the helper writes a temporary source under
`build/mwcc_debug_cache/probes/signature_audit`, invokes `debug dump local`
with `--unit-source <real src>` and `--keep-obj <tmp.o>`, stages the temporary
object under the lock for `tools/checkdiff.py --format json --no-build`, and
restores the original build object on success and on a simulated checkdiff
failure.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_mwcc_debug_signature_audit.py tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff -q
```

Expected: CLI command missing and validation helper missing.

- [ ] **Step 3: Implement validation helper**

In `signature_audit.py`, add:

```python
def validate_signature_patches(
    report: SignatureAuditReport,
    *,
    source_path: Path,
    source_text: str,
    function: str,
    baseline_percent: float | None,
    runner: Callable[[str, str], dict],
) -> SignatureAuditReport:
```

The helper should:

- inspect actions with `patch is not None`;
- replace `patch.old` with `patch.new` exactly once in in-memory source text;
- call `runner(function, patched_source_text)`;
- never write to `source_path`;
- assert `source_path` bytes are unchanged after the runner returns;
- set `action.validation` to `{"status": "improved", "before": ..., "after": ...}`
  when after > before, `matched` when the runner returns `match: True`,
  `no-improvement` when after <= before, and `failed` on exceptions or missing
  replacement text.

- [ ] **Step 4: Implement CLI command**

In `tools/melee-agent/src/cli/debug.py`:

- import `audit_signature_call_type` and `validate_signature_patches`;
- add `@suggest_app.command(name="signatures")`;
- options:
  - `function: --function/-f`;
  - `--checkdiff-json Path | None`;
  - `--validate`;
  - `--checkdiff-timeout float = 120.0`;
  - `--json`;
- when `--checkdiff-json` is present, read it;
- otherwise run `python tools/checkdiff.py <function> --format json` with
  `_checkdiff_env_without_fingerprint()`;
- resolve source via `_find_unit_for_function`;
- call `audit_signature_call_type`;
- if `--validate`, pass a runner that invokes live checkdiff with timeout and
  returns parsed JSON by writing the patched source text to a temporary file,
  compiling it with `debug dump local --unit-source <real src> --keep-obj`, then
  running `tools/checkdiff.py --format json --no-build` against the temporary
  object under `_acquire_checkdiff_repo_lock`;
- print JSON by serializing dataclasses recursively;
- print text with finding kind, call target, source line, confidence, candidate
  actions, patch descriptor, and validation status.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider tools/melee-agent/tests/test_mwcc_debug_signature_audit.py tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff -q
```

Expected: all selected tests pass.

### Task 3: Verification, Smoke, And Issue Closure

**Files:**
- Modify if needed: `tools/melee-agent/tests/test_debug_cli_reorg.py`
- Modify if needed: `tools/melee-agent/src/cli/debug.py`
- Modify if needed: `tools/melee-agent/src/mwcc_debug/signature_audit.py`

- [ ] **Step 1: Run focused regression suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_mwcc_debug_cast_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff \
  -q
```

- [ ] **Step 2: Run command-level smoke checks**

```bash
/opt/homebrew/bin/melee-agent debug suggest signatures --help
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures --help
```

If a saved fixture JSON was created in the test, run the CLI against a temporary
payload through pytest only; do not add repo fixture files unless the tests need
them.

- [ ] **Step 3: Run formatting and syntax checks**

```bash
python -m py_compile \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py
git diff --check
```

- [ ] **Step 4: Commit and resolve issue**

```bash
git add \
  docs/superpowers/specs/2026-06-05-signature-call-type-audit-design.md \
  docs/superpowers/plans/2026-06-05-signature-call-type-audit.md \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py
git commit -m "Add signature call-type audit"
FIX_COMMIT="$(git rev-parse --short HEAD)"
/opt/homebrew/bin/melee-agent issue resolve 428 --note "Fixed in ${FIX_COMMIT}: debug suggest signatures audits checkdiff call-prep signature mismatches and emits source-level candidate actions with optional validation."
```
