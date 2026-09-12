# struct verify #439 completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish issue #439 by teaching `struct verify` to use minimal assembly dataflow for aliased/interior bases and to apply only byte-verified simple layout repairs.

**Architecture:** Keep `checkdiff` as the aligned-instruction source, enrich its offset discrepancy rows with per-side base registers, and let `struct verify` canonicalize those rows with a small assembly dataflow model. Guarded apply generates one candidate header edit at a time and commits only the candidate proven by `struct_layout.verify_offsets`.

**Tech Stack:** Python 3.11, pytest, Typer, existing MWCC `offsetof` probe helpers, `tools/checkdiff.py`.

**Spec:** `docs/superpowers/specs/2026-06-06-struct-verify-439-completion-design.md`

---

## File Structure

- Modify `tools/checkdiff.py`: keep existing `offset_discrepancies` keys and add `ref_base_reg`, `cur_base_reg`, instruction-only `ref_index`, and instruction-only `cur_index`; allow differing physical bases when the mnemonic and memory shape align.
- Modify `tools/melee-agent/src/cli/struct.py`: add assembly lookup, function block extraction, checkdiff JSON asm parsing, separate reference/current register trace dataflow, per-row normalization, and expanded guarded apply helpers.
- Modify `tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py`: cover different physical bases and backward-compatible row fields.
- Modify `tools/melee-agent/tests/test_struct_verify.py`: cover dataflow, CLI no-base alias inference, constant interior normalization, apply pad shrink/removal, field move, and rollback.

## Task 1: Enrich Checkdiff Offset Rows

- [ ] **Step 1: Add failing tests**

In `tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py`, add tests that:

```python
def test_paired_struct_offset_delta_keeps_per_side_bases():
    d = checkdiff._paired_struct_offset_delta("lwz r0,16(r28)", "lwz r0,24(r31)")
    assert d["base_reg"] == "r31"
    assert d["ref_base_reg"] == "r28"
    assert d["cur_base_reg"] == "r31"
    assert d["ref_disp"] == 16
    assert d["cur_disp"] == 24

def test_offset_discrepancies_different_physical_bases_are_reported():
    ref = _lines(["mr r28,r3", "lwz r0,16(r28)", "blr"])
    cur = _lines(["mr r31,r3", "lwz r0,24(r31)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    assert any(d["ref_base_reg"] == "r28" and d["cur_base_reg"] == "r31" for d in od)
```

- [ ] **Step 2: Run focused failing tests**

Run:

```bash
cd /Users/mike/code/melee/tools/melee-agent
python -m pytest tests/test_checkdiff_offset_discrepancies.py::test_paired_struct_offset_delta_keeps_per_side_bases tests/test_checkdiff_offset_discrepancies.py::test_offset_discrepancies_different_physical_bases_are_reported -q
```

Expected: both fail before the production change.

- [ ] **Step 3: Implement row enrichment**

In `tools/checkdiff.py`, update `_paired_struct_offset_delta` so differing non-stack bases no longer reject the row. Return:

```python
{
    "base_reg": cur_base,
    "ref_base_reg": ref_base,
    "cur_base_reg": cur_base,
    "mnemonic": mnemonic,
    "ref_disp": rd,
    "cur_disp": cd,
}
```

Preserve existing exclusion for `r1`, `r2`, and `r13`, preserve `base_reg`
as the current-side base for old callers, and add instruction indices when
rows are emitted from `classify_asm_diff`.

- [ ] **Step 4: Verify task**

Run:

```bash
cd /Users/mike/code/melee/tools/melee-agent
python -m pytest tests/test_checkdiff_offset_discrepancies.py -q
```

Expected: all tests pass.

## Task 2: Add Struct-Verify Dataflow Normalization

- [ ] **Step 1: Add failing pure tests**

In `tools/melee-agent/tests/test_struct_verify.py`, add tests for:

```python
def test_trace_registers_tracks_alias_addi_and_global():
    from src.cli.struct import _trace_registers_from_asm
    traces = _trace_registers_from_asm([
        "mr r28,r3",
        "addi r31,r28,0x20",
        "lwz r30,__THPInfo@sda21(r13)",
    ])
    assert traces["r28"].root == "arg3"
    assert traces["r31"].root == "arg3"
    assert traces["r31"].offset == 0x20
    assert traces["r30"].root == "global:__THPInfo"

def test_trace_registers_invalidates_unknown_writes():
    from src.cli.struct import _trace_registers_from_asm
    traces = _trace_registers_from_asm(["mr r28,r3", "lwz r28,0(r4)"])
    assert "r28" not in traces

def test_resolve_rows_from_dataflow_accepts_same_root_different_regs():
    from src.cli.struct import _resolve_discrepancy_rows
    layout = {"field": 0x24}
    rows, skipped = _resolve_discrepancy_rows(
        "fn",
        [{"ref_base_reg": "r28", "cur_base_reg": "r31", "base_reg": "r31", "cur_disp": 4, "ref_disp": 8}],
        layout,
        traces={"r28": ("arg3", 0, "mr"), "r31": ("arg3", 0x20, "addi")},
    )
    assert not skipped
    assert rows[0]["base_offset"] == 0x20
```

Use the actual helper signatures chosen in production, but keep these assertions.

- [ ] **Step 2: Add failing CLI tests**

Monkeypatch `struct_layout.resolve_layout`, `subprocess.run`, and assembly trace
extraction so a `struct verify` call without `--base` maps a copied argument
register and a constant interior `addi` to the expected absolute field.

- [ ] **Step 3: Implement dataflow helpers**

In `tools/melee-agent/src/cli/struct.py`:

- Add a small `RegisterTrace` dataclass.
- Add `_asm_path_for_tu(repo, tu_src)`, `_function_asm_lines(repo, tu_src, fn)`,
  `_instruction_lines_from_checkdiff_asm(lines)`, `_trace_registers_by_index(lines)`,
  and `_trace_registers_from_asm(lines)`.
- Add `_resolve_discrepancy_rows(...)` that applies explicit base/base-offset
  inputs first, then separate reference/current access-index dataflow traces,
  then the existing unique physical-base fallback only for same-base rows.
- Refactor the command loop to call `_resolve_discrepancy_rows` and pass each
  normalized row to `_finding_from_offset_discrepancy`.

- [ ] **Step 4: Verify task**

Run:

```bash
cd /Users/mike/code/melee/tools/melee-agent
python -m pytest tests/test_struct_verify.py -q
python -m py_compile ../checkdiff.py src/cli/struct.py
```

Expected: all tests pass and py_compile exits zero.

## Task 3: Expand Guarded Apply Repair

- [ ] **Step 1: Add failing apply tests**

In `tools/melee-agent/tests/test_struct_verify.py`, add tests for:

- Shrinking a preceding `u8 pad0[8];` to `u8 pad0[4];` when verification passes.
- Removing a preceding `u8 pad0[4];` when the shrink consumes the whole pad.
- Moving one top-level field before another when verification passes.
- Restoring the original header when every candidate fails verification.

- [ ] **Step 2: Implement repair helper**

Replace `_apply_struct_padding` with `_apply_struct_repair` while retaining
`_apply_struct_padding` as a compatibility wrapper for existing tests. The repair
helper should reject nested/indexed fields, generate candidates in the order pad
insert, pad shrink/remove, field move, call a supplied `verify(expect_map)` or
`verify()` adapter, and restore the original header after failed candidates.

- [ ] **Step 3: Wire CLI apply**

Update `struct_verify_cmd --apply` to compute an affected verification map that
includes the selected field and all known later top-level fields when available,
then call `_apply_struct_repair`. Keep JSON status values `applied`, `failed`,
and `not_applicable`.

- [ ] **Step 4: Verify task**

Run:

```bash
cd /Users/mike/code/melee/tools/melee-agent
python -m pytest tests/test_struct_verify.py -q
melee-agent struct verify --help
```

Expected: tests pass and help shows `--apply`, `--base-offset`, and
`--base-offset-map`.

## Final Verification

- [ ] Run `cd /Users/mike/code/melee/tools/melee-agent && python -m pytest tests/test_checkdiff_offset_discrepancies.py tests/test_struct_verify.py tests/test_struct_layout.py -q`.
- [ ] Run `cd /Users/mike/code/melee && python -m py_compile tools/checkdiff.py tools/melee-agent/src/cli/struct.py tools/melee-agent/src/common/struct_verify.py tools/melee-agent/src/common/struct_layout.py`.
- [ ] Run smoke checks from `/Users/mike/code/melee`: `melee-agent struct verify --help` and one JSON command on a known function if the build artifacts are present.
- [ ] Commit only the spec, plan, tooling, and tests. Do not stage the unrelated dirty `src/sysdolphin/baselib/hsd_3B34.c`.
- [ ] Refresh the editable `melee-agent` install so `/opt/homebrew/bin/melee-agent` imports `/Users/mike/code/melee` current `master`.
