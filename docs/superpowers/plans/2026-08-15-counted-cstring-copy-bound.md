# Counted C-String Copy Bound Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the exact caller-bound counted-string producer and guarded C-string consumer so Task 8 can bound the retail `memcpy` at `0x412278` without weakening generic alias or interval analysis.

**Architecture:** Add three address-independent semantic recognizers to `_DirectCfgRecovery`: the counted writer, guarded copier, and their caller-bound adjacency. Consume the resulting width only in one fresh-query alias continuation inside `_closed_call_argument_slot_is_consumed`; keep the generic alias lattice, TOP, caps, structural cache, and ordinary owned-callee walk unchanged.

**Tech Stack:** Python 3.11, Capstone x86 operands/CFG recovery, immutable alias facts, pytest, project-scoped Ruff through `tools/melee-agent/uv`.

## Global Constraints

- Work only in `/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof` on `codex/issue-1240-retail-pcode-proof`.
- Scope tracked implementation changes to `tools/mwcc_retro/x86_cfg.py`, `tools/melee-agent/tests/test_retro_x86_cfg.py`, this plan/spec, `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`, `.superpowers/sdd/progress.md`, and the 12-hour outlook ledger.
- Preserve all existing dirty Task 8 work. Do not reset, checkout, stash, clean, or stage `.agents/`, `.coverage`, `.pi/`, `tools/melee-agent/uv.lock`, or ignored diagnostics.
- Do not add a retail virtual-address/hash/fingerprint allowlist, raise a limit, accept TOP, or teach the generic interval interpreter arbitrary `REPNE SCASB` semantics.
- All new caches are dictionaries local to one `_closed_call_argument_slot_is_consumed` invocation. No new semantic state may enter the structural scan cache.
- Every long command expected to exceed ten minutes must run in a detached `tmux` session with unique output, stderr, timing, and exit-code files.
- Never run `ruff format`; run `cd tools/melee-agent && uv run ruff check ../mwcc_retro/x86_cfg.py tests/test_retro_x86_cfg.py`.
- The currently active diagnostic session `issue1240_memcpy_context_stop` is read-only instrumentation. Inspect it only at quiet intervals and never signal it merely to start implementation.

---

### Task 1: Build the exact synthetic protocol and capture strict RED

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py` near `repeated_private_stack_memcpy_alias_image` and the private-stack alias continuation tests.

**Interfaces:**
- Consumes: existing `load_large_cfg_program`, `_DirectCfgRecovery`, `build_seed_inventory`, `generous_limits`, `_pushed_call_argument`, `_finite_register_values_before`, `_memcpy_like_function`, and `_closed_call_argument_slot_is_consumed`.
- Produces: `counted_cstring_copy_bound_image(tmp_path, *, mutation: str | None, scratch: int = 0x403000, destination_displacement: int = -0x20, audited_reader: bool = False)` and tests whose function names and parameter IDs all contain `counted_cstring_copy_bound`.

- [x] **Step 1: Add one shared fixture with five core functions and two readers**

  Construct one address-independent synthetic image with:

  ```python
  caller = base
  counted_writer = base + 0x50
  guarded_copier = base + 0x80
  memcpy = base + 0x100
  protected_callee = base + 0x140
  scratch = 0x403000
  source_record = 0x403100
  ```

  The caller must allocate a private frame, call the counted writer as
  `(scratch, source_record)`, call the guarded copier as
  `(scratch, private_destination)`, then make one retail-shaped three-argument
  call into `protected_callee`, track scalar argument 1, explicitly zero that
  argument word, clean all three arguments, and return. The counted writer
  must use the retail semantic sequence:

  ```asm
  push ebx
  push esi
  mov esi,[esp+0x10]
  mov ebx,[esp+0x0c]
  movzx ecx,byte [esi]
  mov eax,esi
  inc eax
  push ecx
  push eax
  push ebx
  call memcpy
  movzx eax,byte [esi]
  add esp,0x0c
  mov byte [ebx+eax],0
  pop esi
  pop ebx
  ret 8
  ```

  The guarded copier must save EDI/EBP, load source argument 0 into EBP,
  derive `EDI = 0xfffffffe - ECX` after a forward zero-byte scan, reject the
  non-`JLE 63` arm without copying, pass the source through two exact owned
  direct reader calls whose results are tested only as scalar/null status,
  and on the accepted arm push `(destination argument 1, source argument 0,
  EDI + 1)` into the same audited `memcpy` body before returning a scalar
  status. Each reader has a distinct recovered function entry and a closed
  read-only/no-escape body.

  The second positive changes both the scratch immediate and destination
  coordinate and replaces the two trivial readers with one compact instance
  of the existing address-independent `_audited_strchr_function` shape. This
  exercises the exact retail interior-or-null reader seam without introducing
  retail addresses or a second fixture family.

- [x] **Step 2: Add the exact mutation table**

  Support these IDs without creating one fixture per case:

  ```python
  COUNTED_CSTRING_COPY_BOUND_CASES = (
      ("valid", None, True),
      ("producer-wide-count", "producer-wide-count", False),
      ("producer-missing-nul", "producer-missing-nul", False),
      ("producer-wrong-nul-index", "producer-wrong-nul-index", False),
      ("scratch-mismatch", "scratch-mismatch", False),
      ("producer-bypass", "producer-bypass", False),
      ("caller-direction-set", "caller-direction-set", False),
      ("intervening-call", "intervening-call", False),
      ("intervening-write", "intervening-write", False),
      ("reader-callee-saved-clobber", "reader-callee-saved-clobber", False),
      ("reader-direction-leak", "reader-direction-leak", False),
      ("scan-accumulator-family", "scan-accumulator-family", False),
      ("scan-address-size", "scan-address-size", False),
      ("scan-count-family", "scan-count-family", False),
      ("scan-count-seed", "scan-count-seed", False),
      ("scan-source", "scan-source", False),
      ("scan-length-sub", "scan-length-sub", False),
      ("guard-bound", "guard-bound", False),
      ("guard-arm", "guard-arm", False),
      ("copy-increment", "copy-increment", False),
      ("copy-length", "copy-length", False),
      ("copy-source", "copy-source", False),
      ("copy-destination", "copy-destination", False),
      ("consumer-stack-drift", "consumer-stack-drift", False),
      ("consumer-wrong-restore", "consumer-wrong-restore", False),
      ("memcpy-body", "memcpy-body", False),
      ("producer-target", "producer-target", False),
      ("consumer-target", "consumer-target", False),
      ("reader-return-pointer-use", "reader-return-pointer-use", False),
      ("pointer-publication", "pointer-publication", False),
      ("destination-register-forwarding", "destination-register-forwarding", False),
      ("pointer-return", "pointer-return", False),
      ("source-top", "source-top", False),
      ("destination-top", "destination-top", False),
      ("authority-leak", "authority-leak", False),
  )
  ```

  Each hostile changes one instruction, edge, operand, or context fact. For
  `authority-leak`, add a second guarded-copier call with no matching producer
  and a distinct stack destination; do not mutate the valid first pair.

- [x] **Step 3: Add non-vacuous direct recognizer prerequisites**

  In `test_counted_cstring_copy_bound_requires_exact_protocol`, recover each
  case and assert:

  ```python
  assert recovery.call_targets_by_source[producer_call] == {counted_writer}
  assert recovery.call_targets_by_source[consumer_call] == {guarded_copier}
  assert recovery.call_targets_by_source[producer_memcpy_call] == {memcpy}
  assert recovery.call_targets_by_source[consumer_memcpy_call] == {memcpy}
  assert recovery.call_targets_by_source[protected_call] == {protected_callee}
  assert recovery._memcpy_like_function(memcpy) is (mutation != "memcpy-body")
  ```

  For the unchanged producer, assert the count register immediately before its
  push is exactly `frozenset(range(256))`. For every case except the deliberate
  producer/consumer target mutations, assert the active call and both argument
  pushes remain owned and ordered.

- [x] **Step 4: Add the strict end-to-end oracle**

  Parameterize `test_counted_cstring_copy_bound_closes_only_certified_aliases`
  over the exact case table. Require both:

  ```python
  assert recovery._closed_call_argument_slot_is_consumed(
      protected_call, 1, caller
  ) is expected
  assert recovery._private_stack_store_is_scalar_quarantined(
      protected_store, protected_callee
  ) is expected
  ```

  Run the valid case twice on the same recovery after clearing only the test's
  call counters; require the same result and one fresh-query classification
  per candidate on each invocation. Add a second positive with a different
  scratch immediate and destination coordinate.

- [x] **Step 5: Capture strict RED before production changes**

  Run:

  ```bash
  cd tools/melee-agent
  uv run pytest tests/test_retro_x86_cfg.py -q \
    -k counted_cstring_copy_bound
  ```

  Expected: the valid cases fail only at the final `is True` call-slot/scalar
  oracles; all one-fact hostile cases pass with `False`; no collection,
  recovery, ownership, call-target, or finite-count prerequisite fails. Save
  the exact node tuple, outcome, duration, and unchanged-production commit in
  the Task 8 report before editing production.

---

### Task 2: Add the address-independent producer and consumer recognizers

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py` adjacent to `_memcpy_like_function` and the private-stack alias proof helpers.
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` from Task 1.

**Interfaces:**
- Consumes: recovered owned instructions, raw/recovered CFG edges, `_pushed_call_argument`, `_finite_operand_values_before`, `_register_definitions_across_blocks`, `_memcpy_like_function`, `_summary_successors`, and `_reachable_within_function`.
- Produces:

  ```python
  def _counted_c_string_writer_bound(
      self, function_entry: int
  ) -> int | None: ...

  def _guarded_c_string_copy_bound(
      self, function_entry: int
  ) -> int | None: ...

  def _caller_bound_counted_c_string_copy_bound(
      self, call_address: int, function_entry: int
  ) -> int | None: ...
  ```

  The first returns `0xff`, the second returns `0x40`, and the third returns
  `0x40` only when the exact caller-bound composition is proven; every decline
  returns `None`.

- [x] **Step 1: Implement `_counted_c_string_writer_bound`**

  Enumerate only instructions reachable from `function_entry`; require every
  owned function instruction to belong to that reachable set. Match the exact
  semantic mnemonic sequence from Task 1, but derive register families,
  stack-argument indexes, the direct `memcpy` target, and return cleanup from
  operands rather than addresses or hashes.

  Require exactly one call, one `MOVZX` byte count load, the same source base
  for the exact `MOV`/`INC` `source + 1` lineage and the reloaded count, the
  same destination base for the `memcpy` argument and NUL store, exact cdecl
  argument ordering, exact raw and recovered successors, and
  `_memcpy_like_function(target)`. Return `0xff` only after all checks pass.

- [x] **Step 2: Run the producer-only slice**

  Run:

  ```bash
  cd tools/melee-agent
  uv run pytest tests/test_retro_x86_cfg.py -q \
    -k 'counted_cstring_copy_bound and producer'
  ```

  Expected: producer positive/direct assertions pass; the complete end-to-end
  positive remains RED because no continuation consumes the recognizer yet.

- [x] **Step 3: Implement `_guarded_c_string_copy_bound`**

  Build a bounded semantic audit over the target's reachable CFG. Require one
  source argument-0 load, one destination argument-1 load, one forward
  `REPNE SCASB`, one `0xfffffffe - remaining_count` length definition, one
  full-width `CMP length, 0x3f`, one exact signed `JLE`, one exact increment,
  and one direct audited `memcpy` call. Verify the `memcpy` pushes are exactly
  destination, original source, and incremented length.

  Prove the copy call is unreachable when the guard instruction is excluded,
  the copy path is the `JLE` target, every other guard arm reaches only scalar
  returns, and every reachable return defines EAX from XOR-zero or an
  immediate. Reject every pointer-derived memory write except the certified
  `memcpy` destination. For any other call receiving the source pointer,
  require an exact owned direct target, a closed raw call domain, and either an
  audited read-only/no-escape argument or the existing address-independent
  `_audited_strchr_function` shape. Any interior-or-null return must have a
  call-result suffix that cannot use it as an address, stored value, pushed
  capability, or visible return. Return `0x40` only after the complete audit.

- [x] **Step 4: Run the consumer-only slice**

  Run:

  ```bash
  cd tools/melee-agent
  uv run pytest tests/test_retro_x86_cfg.py -q \
    -k 'counted_cstring_copy_bound and (scan or guard or copy or pointer)'
  ```

  Expected: every direct consumer shape assertion matches its expected bound;
  the end-to-end positive remains RED until Task 3.

- [x] **Step 5: Implement the caller-bound composition**

  In `_caller_bound_counted_c_string_copy_bound`, require the consumer call to
  have an exact direct target whose guarded bound is `0x40`. Resolve consumer
  source argument 0 to a nonempty finite domain with no zero value. Walk
  backward from the consumer's ordered argument pushes to the closest earlier
  call, capped at 32 instructions. Require that call target's writer bound is
  `0xff`, and resolve writer destination argument 0 to exactly the consumer
  source domain.

  Require the producer call to dominate the consumer by proving the consumer
  is unreachable from function entry when the producer call is excluded. From
  producer continuation to consumer call, require exact singleton fallthrough
  successors and allow only register `MOV`/`LEA`, NOP, and the already bound
  consumer argument PUSH instructions. Reject any explicit memory write,
  call, jump, RET/IRET, stack arithmetic, indirect edge, alternate predecessor,
  or extra producer. Return `min(0x40, 0xff + 1) == 0x40`.

- [x] **Step 6: Run all direct recognizer tests**

  Run the exact `counted_cstring_copy_bound` selection. Expected: all direct
  bound assertions pass; only the end-to-end alias-continuation positives
  remain RED.

---

### Task 3: Consume the bound in one fresh-query alias continuation

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py` inside `_closed_call_argument_slot_is_consumed` beside `scalar_format_alias_continuation` and its call-dispatch use.
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` from Task 1.

**Interfaces:**
- Consumes: `_caller_bound_counted_c_string_copy_bound`, current `call_aliases`, `caller_base`, call-state stack coordinates, and `_project_private_stack_alias_escapes`.
- Produces:

  ```python
  def counted_c_string_alias_continuation(
      caller_entry: int,
      call_source: int,
      target: int,
      aliases: _PrivateStackAliasFact,
      caller_base: _PrivateStackAliasFact,
      escape_demand: tuple[_PrivateStackAliasCoordinate, ...],
  ) -> tuple[bool, _PrivateStackAliasFact | None]: ...
  ```

- [x] **Step 1: Add fresh-query caches and the continuation**

  Add only:

  ```python
  counted_c_string_bound_cache: dict[tuple[int, int], int | None] = {}
  ```

  Cache the static caller/call bound once per outer query. If it is `None`,
  return `(False, None)` so ordinary exact-owned analysis retains authority.
  If recognized, require exact call-state coordinates and two ordered caller
  arguments. Read source from outgoing slot `(sp_basis, sp_offset)` and
  destination from `(sp_basis, sp_offset + 4)`. Require `source == ()` and
  `destination is not None`.

  Build the result from `caller_base`: set EAX and ECX to `()`, set EDX to the
  exact destination alias left by the audited `memcpy` body, preserve all
  other registers and the exact caller private-spill/escaped tuples, then call
  `_project_private_stack_alias_escapes`. Return
  `(True, None)` on any recognized-but-invalid alias/projection fact and
  `(True, projected)` only on success. Do not clear destination spill bytes.

- [x] **Step 2: Insert dispatch before generic owned-callee descent**

  Invoke the continuation after the existing scalar-format continuation and
  before `memcpy_alias_continuation` / generic `exact_owned` descent. Require
  exact direct-target equality and the existing singleton call target set.
  On recognition, require one ordinary return successor, create only the
  caller continuation context with the current assumptions and authority
  fields, enqueue it, and `continue`; never create a callee context for this
  summarized call.

- [x] **Step 3: Run strict GREEN**

  Run:

  ```bash
  cd tools/melee-agent
  uv run pytest tests/test_retro_x86_cfg.py -q \
    -k counted_cstring_copy_bound
  ```

  Expected: every exact node passes, including repeated-query and
  authority-leak cases. Record node count and duration.

- [x] **Step 4: Run adjacent alias/memcpy/formatter regressions**

  Run:

  ```bash
  cd tools/melee-agent
  uv run pytest tests/test_retro_x86_cfg.py -q \
    -k 'counted_cstring_copy_bound or private_stack_alias_tabulation_summarizes_exact_memcpy_effect or format_writer_copy_bound or format_buffer_literal_count or private_stack_scalar_flow'
  ```

  Expected: all pass within the existing two-minute focused ceiling. Confirm
  the existing unknown-length stack-source and stack-destination hostiles
  remain false.

- [x] **Step 5: Run static and scope checks**

  Run:

  ```bash
  python -m py_compile \
    tools/mwcc_retro/x86_cfg.py \
    tools/melee-agent/tests/test_retro_x86_cfg.py
  (cd tools/melee-agent && \
    uv run ruff check ../mwcc_retro/x86_cfg.py tests/test_retro_x86_cfg.py)
  git diff --check
  git status --short
  ```

  Require only the authorized tracked files plus pre-existing ignored/untracked
  artifacts. Scan added production lines for retail virtual addresses, hashes,
  fingerprint allowlists, new persistent caches, or limit changes; the scan
  must be empty.

---

### Task 4: Validate retail, record the boundary, and make it durable

**Files:**
- Modify: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`
- Modify: `.superpowers/sdd/progress.md`
- Modify when due: `.superpowers/sdd/2026-07-12-retail-pcode-proof/outlook-ledger.md`
- Modify: `docs/superpowers/plans/2026-08-15-counted-cstring-copy-bound.md`
- Preserve: ignored `build/diagnostics/task4-repair-exact/hydrate-cfg-query.py` instrumentation and run outputs.

**Interfaces:**
- Consumes: green focused/static gates and the unchanged authoritative call-slot command.
- Produces: one durable implementation commit and the next exact Task 8 boundary.

- [x] **Step 1: Reconcile the diagnostic stop**

  When `issue1240_memcpy_context_stop` exits naturally, record its command,
  duration, max RSS, output/stderr hashes, exact rejected caller/context rows,
  and whether they match the design evidence. If they contradict the selected
  caller-bound producer/consumer relation, stop before retail replay and return
  to root-cause investigation.

- [ ] **Step 2: Start authoritative replay detached**

  Create a unique run directory and launch:

  ```bash
  python -u build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
    --call-slot-consumed 0x443a10 1 0x443770 \
    --fast-call-slot
  ```

  under `/usr/bin/time -l` in detached `tmux`, with separate `output.log`,
  `stderr.log`, and `exit-code.txt`. Do not poll more often than every 15
  minutes. A green boundary is exactly:

  ```text
  call-slot-consumed=0x443a10;argument=1;function=0x443770;result=True
  ```

  If false at a new address/family, document the new first unsupported fact and
  return to systematic root-cause tracing. Do not extend this continuation
  beyond the certified protocol.

- [ ] **Step 3: Run broad gates only after retail GREEN**

  Run the Task 8 focused selection and full x86 module. The full module may run
  normally if its measured duration remains below ten minutes; otherwise
  detach it. Then rerun `py_compile`, project-scoped Ruff, and `git diff
  --check`. Record exact counts, durations, and log hashes.

- [ ] **Step 4: Update report, progress, plan, and ledger**

  Append the RED/GREEN chronology, semantic interfaces, hostile matrix,
  focused/broad/static evidence, diagnostic result, replay result, runtime,
  memory, and hashes to the Task 8 report. Update `.superpowers/sdd/progress.md`
  with the current boundary. Check completed boxes in this plan. If the
  12-hour deadline has arrived, append all five mandatory outlook fields:
  remaining blocker families, replay graph shrink/expansion, definitely
  required replay/review cycles, best/likely/adverse scenarios, and the exact
  reconsideration trigger.

- [ ] **Step 5: Commit and push only the authorized tracked set**

  Review `git diff --cached --name-only` before committing. Stage only the two
  Python files, this design/plan, Task 8 report, progress, and a due ledger
  update. Commit with:

  ```bash
  git commit -m "fix(mwcc-retro): bound counted cstring copies"
  git push origin codex/issue-1240-retail-pcode-proof
  ```

  Require local HEAD and the fork ref to match. Do not claim Task 8 complete
  merely because the call-slot replay is green; proceed next to root
  `0x435620`, independent root `0x435a8c`, exact artifacts, promotion, merge,
  installed replay, issue resolution, claim clear, and queue refresh.
