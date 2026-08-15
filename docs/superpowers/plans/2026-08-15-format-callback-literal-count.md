# Format Callback Literal-Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a formatter callback whose buffer-bounded helper return is paired with one exact literal count, without weakening generic stack-alias analysis.

**Architecture:** Reuse the existing path-sensitive `_audited_format_buffer_end_count` interpreter. Add a second count-origin mode that seeds an exact bounded fact from a positive immediate and leaves all existing source, helper-return, CFG, immutable-format, preservation, cap, and final interval checks in force.

**Tech Stack:** Python 3.11, Capstone-backed recovered x86 CFG fixtures, pytest, Ruff, detached tmux retail replay.

## Global Constraints

- Do not accept TOP as buffer provenance.
- Do not add retail virtual-address, compiler-hash, function-fingerprint, or body-byte allowlists.
- Do not raise `AnalysisLimits` or semantic fact caps.
- Preserve the existing dynamic end-minus-source behavior exactly.
- Every long-running command must run detached and survive a Codex app restart.
- Do not run `ruff format`.

---

### Task 1: Add the literal-count RED matrix

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:49289`

**Interfaces:**
- Consumes: `_DirectCfgRecovery._audited_format_buffer_end_count(call_source, engine, protocol, source_value) -> bool`
- Produces: one recovered-CFG positive plus one-fact hostiles for literal-count buffer callbacks.

- [ ] **Step 1: Add the synthetic fixture and parametrized test**

Add a `test_format_buffer_literal_count_accepts_only_bounded_helper_return`
matrix adjacent to the dynamic helper-return test. Build the engine from this
literal byte sequence, patching the helper displacement as the neighboring test
does:

```python
engine = bytearray(
    bytes.fromhex(
        "55 89 e5 83 ec 40 "
        "8d 44 24 10 "
        "89 44 24 08 "
        "83 44 24 08 1f "
        "89 44 24 0c "
        "83 44 24 0c 20 "
        "ff 74 24 0c "
        "e8 00 00 00 00 "
        "59 89 c6 "
        "6a 01 56 68 00 30 40 00 "
        "ff 55 08 "
        "83 c4 0c c9 c3"
    )
)
helper_body = bytearray(bytes.fromhex("8b 44 24 04 83 e8 01 c3"))
```

Use literal expectations for these IDs:

```python
(
    (None, True),
    ("helper-past-end", False),
    ("wrong-end-forward", False),
    ("zero-count", False),
    ("count-crosses-end", False),
    ("unclassified-source", False),
    ("detached-callback", False),
)
```

Apply one change per hostile: `sub eax,1 -> add eax,1`; forwarded slot
`[esp+0xc] -> [esp+0x8]`; `push 1 -> push 0`; `push 1 -> push 2`;
`mov esi,eax -> mov esi,ecx`; or omit the recovered callback from
`protocol.callback_calls`. Assert the helper target/argument, the indirect
callback callsite and operand (including the absence of a direct target), the
buffer coordinate, literal count operand, and mutation-specific bytes before
asserting the auditor result.

- [ ] **Step 2: Run the strict RED**

Run:

```bash
cd tools/melee-agent
uv run pytest tests/test_retro_x86_cfg.py \
  -k 'format_buffer_literal_count_accepts_only_bounded_helper_return' -vv
```

Expected: seven cases collected; only the positive case fails because the
current auditor requires a register count; all six hostile cases pass.

---

### Task 2: Extend the existing path-sensitive count auditor

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:81478`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: the existing `_FormatCallbackRangeFact`,
  `_audited_reverse_format_helper_return`, and formatter protocol.
- Produces: unchanged method signature and a `True` result for either the
  existing dynamic relation or an exact bounded literal relation.

- [ ] **Step 1: Parse the two count-origin modes**

Keep the source argument requirement unchanged. Replace the register-only count
gate with:

```python
literal_count = None
count_family = None
if count_argument[1].type == X86_OP_IMM:
    literal_count = count_argument[1].imm & 0xFFFF_FFFF
    if literal_count == 0:
        return False
elif count_argument[1].type == X86_OP_REG and count_argument[1].size == 4:
    count_family = self._register_family(count_argument[1].reg)
else:
    return False
```

Require `source_family` to remain callee-saved. When `count_family` is present,
retain the existing distinct/callee-saved checks; the literal mode has no count
register family.

- [ ] **Step 2: Preserve the dynamic guard only for register counts**

For `count_family is not None`, retain the exact preceding `test`/`je` guard,
fallthrough/skipped successor checks, and zero/nonzero fact split byte-for-byte.
For literal mode, set `guard = None` and do not synthesize a branch or
fallthrough fact.

- [ ] **Step 3: Seed and transfer the literal fact**

Initialize the entry set as:

```python
initial_fact = (
    _FormatCallbackRangeFact()
    if literal_count is None
    else _FormatCallbackRangeFact(
        count_kind="bounded",
        count_low=literal_count,
        count_high=literal_count,
    )
)
facts = {engine: {initial_fact}}
```

When `count_family is None`, `transfer_count` returns its incoming fact
unchanged. Audit call preservation only for `(source_family,)`; dynamic mode
continues to audit `(source_family, count_family)`. Keep source transfer,
immutable-format pruning, raw-successor equality, the 16-fact cap, iteration
cap, and `_format_count_fact_covers_sources` unchanged.

- [ ] **Step 4: Run GREEN and regression slices**

Run:

```bash
cd tools/melee-agent
uv run pytest tests/test_retro_x86_cfg.py \
  -k 'format_buffer_literal_count_accepts_only_bounded_helper_return or format_buffer_dynamic_count or format_reverse_helper_return or format_callback_count_fact' -vv
```

Expected: all selected tests pass.

- [ ] **Step 5: Run static checks**

Run:

```bash
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
uvx ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check -- tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
```

Expected: all commands exit zero.

---

### Task 3: Validate the real Task 8 boundary

**Files:**
- Modify after evidence: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`
- Modify after evidence: `.superpowers/sdd/progress.md`
- Modify after evidence: `docs/superpowers/plans/2026-08-13-recursive-stack-residue.md`

**Interfaces:**
- Consumes: the local GREEN implementation.
- Produces: authoritative detached retail result and the next Task 8 boundary.

- [ ] **Step 1: Launch the retail call-slot replay detached**

From the worktree root, choose a fresh run directory and session name, then run:

```bash
run_dir=build/diagnostics/task4-repair-exact/runs/20260815-literal-count-green-tmux
session=issue1240_literal_count_green
mkdir -p "$run_dir"
printf '%s\n' "$session" > "$run_dir/tmux-session.txt"
tmux new-session -d -s "$session" \
  "cd '$PWD' && /usr/bin/time -l python -u \
   build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
   --call-slot-consumed 0x443a10 1 0x443770 --fast-call-slot \
   > '$PWD/$run_dir/output.log' 2> '$PWD/$run_dir/stderr.log'; \
   printf '%s\\n' \$? > '$PWD/$run_dir/exit-code.txt'"
```

Do not poll more often than every 15 minutes. The authoritative condition is a
completed semantic row whose `result=True`, not merely shell exit zero.

- [ ] **Step 2: If retail is GREEN, run focused/full/static gates**

Run the exact focused selector and complete module:

```bash
python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'private_stack_scalar or private_stack_residue or noescape_scalar or partial_return or partial_register or session_capability_seal or narrow_scalar_argument or format or writer or stream'
python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
uvx ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
```

The first selector previously collected 684 of 3,633 cases; update the expected
total to include the new seven-case matrix and require every literal-count ID to
be present. Run commands expected to exceed ten minutes in a fresh detached
tmux directory with stdout, stderr, `exit-code.txt`, elapsed time, RSS, and
SHA-256 recorded.

- [ ] **Step 3: Record evidence and commit the implementation slice**

Append exact test counts, timings, run-directory paths, semantic result rows,
and output digests to the Task 8 report/progress documents. Stage only the
authorized tracked files, verify the cached diff and staged scope, then commit:

```bash
git commit -m "fix(mwcc-retro): prove literal-count format callbacks"
```

Do not claim Task 8 complete unless the retail call-slot result and all local
gates are green. If retail advances to a new semantic boundary, document that
boundary and return to systematic debugging.
