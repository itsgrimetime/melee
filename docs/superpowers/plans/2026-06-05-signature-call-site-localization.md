# Signature Call-Site Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make `debug suggest signatures` resolve checkdiff `R_PPC_REL24` callees and produce source-localized or narrowly rebucketed findings instead of universal `call-not-localized`.

**Architecture:** Keep all behavior in `tools/melee-agent/src/mwcc_debug/signature_audit.py`. Extend the existing ASM call model with relocation/display targets and the source context with exact plus diagnostic overall-ordinal lookup.

**Tech Stack:** Python dataclasses, existing checkdiff JSON parser, existing synthetic signature-audit pytest tests, live CLI smoke for `fn_8019F9C4`.

---

## Task 1: Relocation-Aware ASM Call Targets

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] Write a failing test where target/current ASM both contain
  `bl <caller_fn+0x20>` plus same-offset `R_PPC_REL24 helper`, with a bank
  mismatch. Assert the finding is `argument-bank-mismatch`, localized to
  source helper call line/argument, and has no false call-target-shape finding.
- [x] Run the single test and confirm it fails because the current parser uses
  `caller_fn+0x20`.
- [x] Add `display_target` and `relocation_target` to `_AsmCall`.
- [x] Add helpers that parse line offsets and same-offset `R_PPC_REL24` targets.
- [x] Use `relocation_target or display_target` as `_AsmCall.call_target`.
- [x] Include `display_target` and `relocation_target` in `_call_shape_dict()`.
- [x] Rerun the single test and confirm it passes.

## Task 2: Safe Source Localization Fallbacks

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] Write a failing test where an external ASM callee does not match source
  spelling but has the same overall ordinal. Assert affected call-site metadata
  includes the source line, source callee, argument text, and
  `localization_kind="overall-ordinal"`, but no patch candidate is emitted.
- [x] Write a failing test where unresolved `caller_fn+0x20` has no relocation;
  assert it does not map to the first source helper call and rebuckets to
  `intra-function-branch-link`.
- [x] Write a failing test where a call has `R_PPC_REL24 generated_helper` but
  no source call expression. Assert it rebuckets to
  `relocated-call-not-in-source`.
- [x] Add `function` and `call_sites_by_overall` to `_SourceContext`.
- [x] Filter `PAD_STACK` and `void` parser artifacts inside
  `_build_source_context()`.
- [x] Update `_source_site_for_call()` lookup order: exact, unresolved-local
  stop, diagnostic overall ordinal, then existing target first-occurrence
  fallback.
- [x] Mark source sites with `localization_kind`.
- [x] Prevent `_remove_cast_action()` from using `overall-ordinal` localized
  source sites.
- [x] Rerun the new tests and confirm they pass.

## Task 3: Narrow Structural Rebucket For Local Offset Branch-Links

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/signature_audit.py`
- Modify: `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`

- [x] Write a failing call-target-shape test where expected/current unresolved
  targets are `caller_fn+0x20` and `caller_fn+0x24`. Assert the action rebucket
  reason is `intra-function-branch-link`, not `call-not-localized`.
- [x] Pass call context into `_call_target_rebucket()` and
  `_argument_rebucket()`.
- [x] Add `_is_unresolved_function_offset_call()` using `display_target`,
  `relocation_target`, and the source context function name.
- [x] Emit `intra-function-branch-link` for unresolved function-local offset
  targets with no relocation target.
- [x] Emit `relocated-call-not-in-source` for relocated calls that have no
  matching source call expression.
- [x] Rerun the new test and affected existing rebucket tests.

## Task 4: Verification, Commit, Install, Resolve

**Files:**
- All changed files.

- [x] Run focused pytest:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= pytest --no-cov -p no:cacheprovider \
  tools/melee-agent/tests/test_mwcc_debug_signature_audit.py \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_json_from_saved_checkdiff \
  tools/melee-agent/tests/test_debug_cli_reorg.py::test_debug_suggest_signatures_text_prints_summary_and_rebucket \
  -q
```

- [x] Run syntax and help smokes:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  tools/melee-agent/src/mwcc_debug/signature_audit.py \
  tools/melee-agent/src/cli/debug.py
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures --help
```

- [x] Run live `fn_8019F9C4` smoke and assert `call-not-localized` is absent:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug suggest signatures \
  -f fn_8019F9C4 --json
```

- [x] Run `git diff --check`, stage intended files with `git add -f` for
  ignored `tools/melee-agent` files, commit, refresh editable install from
  `/Users/mike/code/melee`, resolve issue #431, and verify no open issues.
