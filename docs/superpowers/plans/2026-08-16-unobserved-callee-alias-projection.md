# Unobserved Callee Alias Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit the exact Task 8 owned-call prefix when stack alignment expands only a provably unobserved incoming register alias set beyond the finite coordinate cap, without weakening observed inputs, TOP, caps, or return currentness.

**Architecture:** Project a non-`ESP`/`EBP` register to the non-stack input element only after `_function_reads_incoming_register(callee, family)` proves the complete transitive callee body never observes it. Reuse the existing return-effect selection so unchanged/callee-saved outputs restore the caller value, proven kills select the callee output, and genuinely new outputs remain mapped normally.

**Tech Stack:** Python 3.11, Capstone x86 decoding, `_DirectCfgRecovery`, pytest, Ruff, git, detached tmux validation wrappers.

## Global Constraints

- Keep the exact alias-value cap at 64 and every existing `AnalysisLimits` bound unchanged.
- Do not accept TOP, unresolved/imported edges, partial reads, memory/address uses, raw/recovered domain mismatch, or stale summary facts.
- Do not add retail addresses, hashes, compiler markers, or allowlists to production.
- Keep changes to `tools/mwcc_retro/x86_cfg.py`, `tools/melee-agent/tests/test_retro_x86_cfg.py`, and the existing Task 8 handoff/report files.
- Run any expected 5--10+ minute command in a restart-safe detached session.

---

### Task 1: Lock the aligned unobserved-input boundary with strict TDD

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_DirectCfgRecovery._closed_call_argument_slot_is_consumed(call_address: int, argument_index: int, function_entry: int) -> bool`, `_function_reads_incoming_register(function_entry: int, register_family: str) -> bool`, and the existing synthetic PE helpers.
- Produces: `aligned_unobserved_callee_alias_image(...)` and a named positive/hostile test selection that fails only at the current alias-entry projection boundary.

- [ ] **Step 1: Add one shared aligned-caller fixture**

Build a synthetic image with these exact semantic facts:

```python
def aligned_unobserved_callee_alias_image(tmp_path, *, mutation=None):
    assert mutation in {None, "observed", "killed", "new-alias"}
    # The entry wrapper selects nine disjoint ESI stack aliases on nine CFG
    # arms, then calls an owned root.  The root aligns ESP to 8 bytes and
    # carries incoming ESI into one nested protected call.  Mapping nine
    # separated basis-0 aliases through eight alignment paddings requires 72
    # exact callee coordinates on unchanged production.
    #
    # None: callee never observes ESI and preserves it.
    # observed: callee dereferences ESI and publishes the loaded word.
    # killed: callee kills ESI before any use and returns the scalar value.
    # new-alias: callee replaces ESI with one new private-stack address, returns
    # it, and the caller publishes through it.  This exercises ordinary output
    # mapping rather than caller-value restoration and must remain negative.
```

Use direct owned call encodings, exact raw/recovered successors, a real
`and esp, -8` alignment instruction, a four-byte protected slot that the root
overwrites before return, and a terminal wrapper suffix that clears caller
aliases before the existing exact `ExitProcess` boundary.

- [ ] **Step 2: Add the positive and hostile assertions**

```python
@pytest.mark.parametrize(
    ("mutation", "expected"),
    ((None, True), ("observed", False), ("killed", True), ("new-alias", False)),
    ids=("unobserved-preserved", "observed-publication", "unobserved-kill", "new-return-alias"),
)
def test_private_stack_alias_projects_only_unobserved_aligned_callee_input(
    tmp_path, mutation, expected
):
    image, root, callee, protected_call, store = (
        aligned_unobserved_callee_alias_image(tmp_path, mutation=mutation)
    )
    recovery = _DirectCfgRecovery(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )
    recovery.recover()

    assert recovery.call_targets_by_source[protected_call] == {callee}
    assert recovery._function_private_stack_coordinate_states(root) is not None
    assert recovery._function_reads_incoming_register(callee, "esi") is (
        mutation == "observed"
    )
    assert recovery._closed_call_argument_slot_is_consumed(
        protected_call, 0, root
    ) is expected
    assert recovery._private_stack_store_is_scalar_quarantined(store, callee) is expected
```

The new-return-alias case must assert that the callee's returned `ESI` is a new
private-stack coordinate and that the caller performs the publication.  It
remains `False`; do not let input projection restore the old caller value and
hide the callee's new output.

- [ ] **Step 3: Run the strict RED selection**

Run:

```bash
pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'private_stack_alias_projects_only_unobserved_aligned_callee_input'
```

Expected on unchanged production: the unobserved-preserved positive fails only
because `_closed_call_argument_slot_is_consumed(...)` is `False`; the observing
hostile remains `False`; all call-domain, alignment, input-read, store, and
non-vacuity assertions pass. Fix fixture mistakes until this exact RED is
obtained before editing production.

- [ ] **Step 4: Preserve the RED without committing a failing tree**

Record the exact command, count, failure boundary, and unchanged-production
commit in the ignored Task 8 report. Retain the unstaged test-first diff for
Task 2; do not create a red branch commit.

---

### Task 2: Project only complete unobserved callee register inputs

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:105377-105478`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: `_function_reads_incoming_register(callee_entry, family)` and existing `map_aliases_to_callee` / `map_aliases_to_caller` return semantics.
- Produces: the same `_PrivateStackAliasFact | None` interface; no durable schema, cap, or cache-key change.

- [ ] **Step 1: Implement the minimal per-register projection**

Inside the `map_aliases_to_callee` register loop, retain the existing empty
`ESP`/`EBP` treatment and add only this semantic choice:

```python
if family in {"esp", "ebp"}:
    mapped = ()
elif not self._function_reads_incoming_register(callee_entry, family):
    mapped = ()
else:
    mapped = map_value(value)
```

Keep `mapped is False -> None`, private-spill mapping, escape projection, and
all 64-point checks unchanged. Add a short comment that unchanged projected
inputs are restored from `caller_base` by `map_aliases_to_caller`; this is not
a generic scalarization rule.

- [ ] **Step 2: Run the strict GREEN selection**

Run the exact Task 1 command. Expected: every selected case passes, with the
observing/publication hostile still negative and no assertion weakened.

- [ ] **Step 3: Run adjacent semantic gates**

```bash
pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py -k \
  'private_stack_residue_alias or private_stack_alias or incoming_register or prologue_save or private_stack_scalar_flow'
```

Expected: all selected tests pass. Inspect `--collect-only` and record the
exact count so a naming mismatch cannot silently deselect the new matrix.

- [ ] **Step 4: Verify exact retail prerequisites**

Run the existing hydrated mini-query for the blocked callee and require:

```text
incoming-register-read=0x4058c0;family=esi;result=False
```

Also dump `0x402c20` and `0x4058c0` from the same current recovery and retain
the exact `and esp, 0xfffffff8`, call `0x402d5c -> 0x4058c0`, and no-ESI-use
body evidence. This is diagnostic/currentness evidence, not an address gate in
production.

- [ ] **Step 5: Run static and scope gates**

```bash
python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
git diff --name-only
git diff -U0 -- tools/mwcc_retro/x86_cfg.py | rg -n -i \
  '0x40|retail|sha|hash|allowlist|ninji|compiler'
```

Expected: compile/Ruff/diff checks pass, scope is the two Python files plus
approved handoff docs, and the added-production-line scan has no match.

- [ ] **Step 6: Commit and push the bounded repair**

```bash
git add tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  .superpowers/sdd/progress.md
git commit -m "fix(mwcc-retro): project unobserved callee aliases"
git push origin HEAD
```

Do not force-add ignored reports or ledgers.

---

### Task 3: Revalidate Task 8 and resume the root sequence

**Files:**
- Modify: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md` (ignored handoff only)
- Modify: `.superpowers/sdd/progress.md` when the result changes materially

**Interfaces:**
- Consumes: the strict repair commit and the existing authenticated wrapper sequence.
- Produces: a current exact call-slot result, then the first-root result if and only if call-slot is positive.

- [ ] **Step 1: Run the complete x86 module gate**

Launch `pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py` with
`/usr/bin/time -l` in a detached tmux session and durable directory containing
`started-at.txt`, `finished-at.txt`, `exit-code.txt`, stdout/stderr, SHA-256
rows, and a wrapper hash. Require exact exit zero.

- [ ] **Step 2: Run the authoritative call-slot replay detached**

Copy the authenticated wrapper structure from
`20260816-reverse-scan-call-slot-authoritative`, update only the run directory,
and require exactly one row matching:

```text
call-slot-consumed=0x443a10;argument=1;function=0x443770;result=True;trace-count=<integer>
```

Inspect at 15-minute quiet intervals. If false, stop before root launch and
reduce the first new fact through another strict TDD cycle.

- [ ] **Step 3: Launch root `0x435620` only after call-slot is positive**

Use the already syntax-checked root wrapper and require one correctly rooted
`result=True` certificate. Keep `0x435a8c` gated until `0x435620` is durable.

- [ ] **Step 4: Continue the governing Task 8 plan**

After both roots are positive, perform the broad adversarial/static review,
immutable run1/run2 generation, resolver-only currentness/equality replay,
Tasks 9--10 promotion, divergent merge rehearsal/real merge, installed CLI
replay, issue resolution, claim clear, and queue refresh. This bounded repair
does not redefine Task 8 or issue #1240 completion.
