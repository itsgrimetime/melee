# Struct Verify Auto-Struct Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve #456 by letting `melee-agent struct verify` infer a unique, resolver-proved struct identity when `--struct` is omitted.

**Architecture:** Add a conservative source candidate collector to `tools/melee-agent/src/cli/struct.py`, then score those candidates through the existing layout/dataflow resolver. Preserve the explicit `--struct` path, add struct-aware aggregation, and update taxonomy next commands to rely on auto-struct mode.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `struct_layout.resolve_layout()` and `_resolve_discrepancy_rows()`.

---

Spec: `docs/superpowers/specs/2026-06-06-struct-verify-auto-struct-design.md`
Issue: #456

## Files

- Modify: `tools/melee-agent/src/cli/struct.py`
- Modify: `tools/melee-agent/src/common/struct_verify.py`
- Modify: `tools/melee-agent/tests/test_struct_verify.py`
- Modify: `tools/function_taxonomy_inventory.py`
- Modify: `tools/melee-agent/tests/test_function_taxonomy_inventory.py`
- Create: `docs/superpowers/specs/2026-06-06-struct-verify-auto-struct-design.md`
- Create: `docs/superpowers/plans/2026-06-06-struct-verify-auto-struct.md`

## Task 1 - Source Identity Candidates

- [x] Add tests in `tools/melee-agent/tests/test_struct_verify.py` for a pure helper named `_struct_identity_candidates_from_source`.
  The tests should cover:
  - `void fn(CameraBounds* bounds, CameraTransformState* state)` yields `CameraTransformState` with root `arg4`.
  - `Fighter* fp = GET_FIGHTER(gobj);` and `Fighter* fp = gobj->user_data;` yield `Fighter` with root `arg3:user_data`.
  - `static THPFileInfo* __THPInfo;` plus `THPFileInfo* info = __THPInfo;` yields `THPFileInfo` with root `global:__THPInfo`.
  - `return gm_8018F634()->cur_option;` plus `TmData* gm_8018F634(void)` yields `TmData` with root `call:gm_8018F634`.
  - Direct global object access `lbl_8046DBD8.x0` plus `static lbl_8046DBD8_t lbl_8046DBD8;` yields `lbl_8046DBD8_t` with root `global:lbl_8046DBD8`.
- [x] Run those tests and verify they fail because the helper does not exist.
- [x] Add a frozen dataclass in `tools/melee-agent/src/cli/struct.py`:

```python
@dataclass(frozen=True)
class StructIdentityCandidate:
    struct: str
    root: str | None
    evidence: str
```

- [x] Implement `_struct_identity_candidates_from_source(source_text: str, function: str) -> list[StructIdentityCandidate]`.
  Use `source_patch.find_function()` for the target function span. Parse only the function signature/body plus TU/global declarations and declarations referenced by the body. Normalize `struct Foo*` and `Foo*` to `Foo`, reject primitives and `void`, and de-duplicate by `(struct, root)`.
- [x] Add a small `_read_tu_with_local_includes(repo: Path, tu_src: str) -> str` helper that appends directly quoted local includes resolved relative to the TU directory or repo source roots.
- [x] Run the new source-candidate tests and verify they pass.

## Task 2 - Resolver-Proved Auto Selection

- [x] Add tests in `tools/melee-agent/tests/test_struct_verify.py` for a pure selector helper. Use monkeypatched layout maps rather than compiling MWCC probes.
  Required cases:
  - Unique matching candidate emits findings with `struct`.
  - A candidate whose root does not match `dataflow:arg4` is rejected even if offsets map.
  - Equal-score candidates produce an `auto-struct ambiguous` skip.
  - No named-field mappings produce an `auto-struct unresolved` skip.
- [x] Run these selector tests and verify they fail.
- [x] Implement a helper in `tools/melee-agent/src/cli/struct.py` that scores candidates by:
  - resolving/caching `struct_layout.resolve_layout(repo, candidate.struct, tu_src)`
  - running `_resolve_discrepancy_rows()` with the same base/base-offset maps and asm trace snapshots as explicit mode
  - converting rows with `_finding_from_offset_discrepancy()`
  - requiring candidate root agreement when resolved rows report `base_reg_source` starting with `dataflow:`
  - selecting only one best candidate with at least one named-field finding
- [x] Attach `finding["struct"] = selected.struct` and `finding["struct_source"] = selected.evidence` for auto mode.
- [x] Run the selector tests and verify they pass.

## Task 3 - CLI Optional `--struct`

- [x] Add CLI tests in `tools/melee-agent/tests/test_struct_verify.py`:
  - `struct verify --help` does not mark `--struct` required.
  - Explicit `--struct Fake` still follows the existing path and emits `struct: "Fake"` in JSON findings.
  - Omitted `--struct` calls the auto selector and emits findings for a mocked second-argument struct parameter.
  - Omitted `--struct` with no candidates emits a skip reason containing `auto-struct`.
- [x] Run those CLI tests and verify they fail.
- [x] Change `struct_verify_cmd` so `struct: Optional[str] = None`.
- [x] Keep explicit mode resolving the layout once before the function loop.
- [x] In omitted mode, read source with `_read_tu_with_local_includes()`, collect candidates per function, run the selector, and extend `findings` or `skipped` from its result.
- [x] Keep `--apply` guarded: if `struct` is omitted and findings aggregate to an apply candidate, use the selected struct for header lookup; otherwise return the existing not-applicable reasons.
- [x] Run the CLI tests and verify they pass.

## Task 4 - Struct-Aware Aggregation and Taxonomy Command

- [x] Add aggregation tests in `tools/melee-agent/tests/test_struct_verify.py` showing two findings with the same `field` but different `struct` remain separate aggregate rows.
- [x] Add taxonomy tests in `tools/melee-agent/tests/test_function_taxonomy_inventory.py` showing the struct-offset next command omits `--struct <struct-name>`.
- [x] Run these tests and verify they fail.
- [x] Update `tools/melee-agent/src/common/struct_verify.py` so `aggregate()` groups by `(finding.get("struct"), finding["field"])` and includes `struct` when present.
- [x] Update `tools/function_taxonomy_inventory.py` so the struct-offset next command is:

```bash
melee-agent struct verify <function><base_arg> --tu-src <source_path> --json
```

- [x] Run the aggregation and taxonomy tests and verify they pass.

## Task 5 - Verification and Issue Resolution

- [x] Run focused tests:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_struct_verify.py -q
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py -q
```

- [x] Run CLI smokes:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli struct verify --help
PYTHONPATH=tools/melee-agent python -m src.cli struct verify Camera_8002A0C0 --tu-src src/melee/cm/camera.c --json
PYTHONPATH=tools/melee-agent python -m src.cli struct verify __THPReadHuffmanTableSpecification --tu-src extern/dolphin/src/dolphin/thp/THPDec.c --json
```

- [x] Run hygiene checks:

```bash
python -m py_compile tools/melee-agent/src/cli/struct.py tools/melee-agent/src/common/struct_verify.py tools/function_taxonomy_inventory.py
git diff --check
```

- [x] Request independent Codex review of the implemented diff.
- [x] Commit only the #456 spec, plan, code, and tests.
- [x] Resolve #456 with the commit hash.
- [x] Refresh the editable `melee-agent` install from `/Users/mike/code/melee`.
