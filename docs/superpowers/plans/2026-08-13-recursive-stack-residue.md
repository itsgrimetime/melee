# Recursive Stack Residue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the private-stack scalar-quarantine proof close recursive outgoing argument residue with a finite, sound interprocedural fixed point.

**Architecture:** Extract an immutable exact-row/dense-tail residue lattice, audit stack aliases from each function entry, and replace concrete continuation growth in `_closed_call_argument_slot_is_consumed` with a query-local call/return tabulation graph. Every join is monotone, every unknown edge rejects, and a widened tail closes only at the exact trusted `kernel32.dll!ExitProcess` contract.

**Tech Stack:** Python 3.11, Capstone x86 decoding, pytest, the existing pinned retail CFG hydration diagnostic.

## Global Constraints

- Production code may not contain a retail address, hash, compiler-build allowlist, or function-shape special case.
- The sole terminal boundary is the exact existing contract `("kernel32.dll", "ExitProcess", None, 1)` plus an empty recovered successor domain.
- Unresolved, indirect, ordinary-import, or other unowned calls reject while any exact residue row or dense tail is live.
- Dense tails, recurrence state, subscribers, and stack-alias state are query-local and are never serialized or reused as certificate authority.
- Existing `max_summary_iterations`, `max_contexts_per_entry`, 64-row, finite-index, and `[-0x1000, 0x1000]` exact-coordinate bounds remain fail-closed; no retail-specific limit increase is permitted. Charge `max_contexts_per_entry` per canonical semantic `(owner entry, start address)`, with the aggregate query still bounded by `max_summary_iterations`.
- Scope is `tools/mwcc_retro/x86_cfg.py`, `tools/melee-agent/tests/test_retro_x86_cfg.py`, this plan/spec, and the existing Task 8 report/ledger only.
- Do not stage `.agents/`, `.coverage`, `.pi/`, `tools/melee-agent/uv.lock`, or ignored diagnostics.
- Do not run the full approximately 16-minute publication-root replay until the focused suite and exact `0x4439ae` mini-query are green.

---

### Task 1: Exact-row and dense-tail lattice

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py` near `_PrivateStackCoordinateState` and `_closed_call_argument_slot_is_consumed`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` near the private-stack scalar-flow unit tests

**Interfaces:**
- Consumes: the existing row tuple `(offset, live_mask, correlations)`.
- Produces: `_PrivateStackResidueFact`, `_normalize_private_stack_residue`, `_join_private_stack_residue`, `_translate_private_stack_residue`, `_overwrite_private_stack_residue`, `_push_private_stack_residue`, and `_pop_private_stack_residue`.

- [x] **Step 1: Add strict lattice REDs**

  Import the new private interfaces from `tools.mwcc_retro.x86_cfg` and add these exact tests:

  ```python
  def test_private_stack_residue_join_preserves_tail_and_stationary_rows():
      left = _PrivateStackResidueFact(((-4, 0xF, ()),), -16)
      right = _PrivateStackResidueFact(((-4, 0x3, ()),), -8)
      assert _join_private_stack_residue(left, right) == (
          _PrivateStackResidueFact(((-4, 0xF, ()),), -8)
      )

  def test_private_stack_residue_branch_join_restores_preserved_tail():
      original = _PrivateStackResidueFact((), -5)
      shortened = _overwrite_private_stack_residue(
          original,
          ((-8, -4),),
      )
      assert shortened.tail_upper == -9
      assert _join_private_stack_residue(
          original,
          shortened,
      ).tail_upper == -5

  @pytest.mark.parametrize(
      ("upper", "expected"),
      ((-8, -4), (-4, -1), (-1, -1), (0, 4)),
  )
  def test_private_stack_residue_push_tail_transfer(upper, expected):
      assert _push_private_stack_residue(
          _PrivateStackResidueFact((), upper)
      ).tail_upper == expected

  def test_private_stack_residue_overwrite_requires_every_address():
      value = _PrivateStackResidueFact((), -5)
      assert _overwrite_private_stack_residue(
          value,
          ((-8, -4), (-4, 0)),
      ).tail_upper == -5

  def test_private_stack_residue_pop_retains_physical_bytes():
      value = _PrivateStackResidueFact(((0, 0xF, ()),), None)
      popped, observed = _pop_private_stack_residue(value)
      assert observed
      assert popped.rows == ((-4, 0xF, ()),)
  ```

  Use half-open byte intervals in production/tests even though the comments above show inclusive endpoints conceptually. Add paired exact-row cases for a row at `-2` straddling PUSH/CALL and a row at `2` straddling POP/RET.

- [x] **Step 2: Run and record strict RED**

  Run:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_residue_'
  ```

  Expected: collection errors only because the six new interfaces do not exist. Existing tests must still collect.

- [x] **Step 3: Add the immutable residue fact**

  Add a module-level frozen/slotted dataclass:

  ```python
  _PrivateStackResidueRow = tuple[
      int,
      int,
      tuple[tuple[int, int], ...],
  ]

  @dataclass(frozen=True, slots=True)
  class _PrivateStackResidueFact:
      rows: tuple[_PrivateStackResidueRow, ...]
      tail_upper: int | None
  ```

  `_normalize_private_stack_residue` must merge masks by exact `(offset, correlations)`, reject offsets outside `[-0x1000, 0x1000]`, reject more than 64 exact rows, and remove rows/bytes subsumed by a tail. It must never turn an empty exact set plus a non-null tail into an empty fact.

- [x] **Step 4: Implement monotone joins and translations**

  `_join_private_stack_residue(left, right)` uses `max` for two tail bounds, preserves the non-null bound when only one side has a tail, ORs exact masks, unions correlation alternatives conservatively, and retains exact bytes above the tail. `_translate_private_stack_residue(fact, delta)` shifts every exact offset and `tail_upper` by the same signed delta and re-normalizes.

  `_overwrite_private_stack_residue(fact, half_open_intervals)` clears an exact byte only if every feasible interval covers it. It shrinks a tail only if every interval covers the current upper byte; the new upper is `max(start for start, _end in intervals) - 1`. A finite overwrite never returns `tail_upper=None`.

- [x] **Step 5: Implement implicit stack transfers**

  `_push_private_stack_residue` first removes exact bytes guaranteed overwritten in `[-4, 0)`, then translates by `+4`. Its tail transfer is exactly:

  ```python
  if upper < -4:
      new_upper = upper + 4
  elif upper < 0:
      new_upper = -1
  else:
      new_upper = upper + 4
  ```

  `_pop_private_stack_residue(fact) -> tuple[_PrivateStackResidueFact, bool]`
  reports whether `[0, 4)` overlaps before translating by `-4`. When the
  caller separately proves the destination suffix closed, the bytes remain in
  the returned fact. RET uses the same observation check but may never waive
  overlap and translates safe facts by `-4-cleanup`.

- [x] **Step 6: Run focused GREEN and static checks**

  Run the Step 2 command, then:

  ```bash
  python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git diff --check
  ```

  Expected: all lattice tests pass; no production call site uses the tail yet.

---

### Task 2: Exact x86 transfer and cache-currentness repair

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:95606` (`_closed_call_argument_slot_is_consumed`)
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` near `test_private_stack_scalar_flow_closes_incoming_argument_slot`

**Interfaces:**
- Consumes: Task 1 residue helpers with `tail_upper=None` on all existing paths.
- Produces: byte-accurate PUSH/CALL/POP/RET handling, explicit-before-implicit operand order, fail-closed unowned calls, exact terminal-contract recognition, and current scalar-quarantine cache keys.

- [ ] **Step 1: Add exact-row RED fixtures**

  Extend `incoming_argument_scalar_quarantine_image` with named one-fact mutations and assert the baseline call topology plus non-null recovery in every case:

  ```text
  pop-stale-reload:
      pop ecx; xor ecx,ecx; mov eax,[esp-4]; mov [global],eax
  push-straddle:
      align row at -2; push harmless; later read surviving bytes
  pop-straddle:
      align row at +2; pop ecx; later read rebased surviving bytes
  push-memory-source:
      push [esp-4]
  call-memory-source:
      call [esp-4]
  zero-arg-unresolved-exact-row:
      call unresolved; callee-shaped bytes allocate down and publish residue
  wrong-dll-exitprocess:
      import name ExitProcess from user32.dll
  wrong-arity-exitprocess:
      kernel32.dll ExitProcess row with arity not equal to one
  ret-cleanup:
      safe `ret 8` control and one overlap hostile
  ```

  Require every hostile's `_closed_call_argument_slot_is_consumed(...)` to be false. The safe nonzero-cleanup control must retain true.

- [ ] **Step 2: Add cache-currentness RED**

  First run a fixture to true through `_private_stack_store_is_scalar_quarantined`. Mutate one raw successor or direct-call target in the same recovery without changing instruction count, increment `control_flow_revision` or change `_summary_fact_signature()`, and require the second call to reject. Assert the old cache key and new key differ. The test name is:

  ```python
  def test_private_stack_scalar_quarantine_cache_tracks_summary_currentness(...):
      ...
  ```

- [ ] **Step 3: Run strict RED**

  Run:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'slot_residue or scalar_quarantine_cache_tracks_summary_currentness or closes_incoming_argument_slot'
  ```

  Expected: the new exact-row soundness/currentness assertions fail while the existing baseline controls pass.

- [ ] **Step 4: Replace nested row mechanics with Task 1 facts**

  Convert the current `slot_rows` state to `_PrivateStackResidueFact(slot_rows, None)`. Delete the duplicated nested normalize/translate implementations. Call `stack_reference_status` before implicit PUSH/CALL handling so explicit memory operands are always audited first.

  For a pure write with multiple finite addresses, pass the complete interval tuple to `_overwrite_private_stack_residue`; do not loop and accept one alternative. Reject segment overrides and unresolved/index-over-budget addresses exactly as before.

- [ ] **Step 5: Repair implicit operations and call boundaries**

  Use byte masks for implicit intervals. POP may accept an overlapping read only for a full-width ECX/EDX destination whose capability-specific suffix is closed, but it must retain and rebase the physical bytes. RET/IRET overlap always rejects.

  Reject unresolved, indirect, ordinary imports, and other unowned calls whenever `fact.rows` or `fact.tail_upper` is nonempty. Recognize the terminal shortcut only by matching the complete normalized `_EXACT_STDCALL_IMPORT_ARITIES` tuple `("kernel32.dll", "ExitProcess", None, 1)`, validating one argument, and requiring `_summary_successors(...) == ()`.

- [ ] **Step 6: Repair scalar-quarantine currentness**

  Change `private_stack_scalar_quarantine_cache` keys to include `_summary_fact_signature()` and `control_flow_revision`. Keep active-recursion keys identical to cache keys. Do not use instruction count as a substitute for the signature.

- [ ] **Step 7: Run GREEN and adjacency**

  Run the Step 3 command and:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_scalar or call_argument_slot or noescape_scalar or partial_return'
  ```

  Expected: new hostiles reject, controls admit, and no test reaches a tail yet.

---

### Task 3: Query-local pre-live stack-alias closure

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py` adjacent to private-stack coordinate helpers and `_closed_call_argument_slot_is_consumed`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` near the Task 2 fixtures

**Interfaces:**
- Consumes: current private-stack coordinate states, exact direct-call domains, register-family helpers, and Task 1 residue facts.
- Produces: `_PrivateStackAliasFact` and `_private_stack_alias_states_for_residue_query(function_entry)`, both query-local.

- [ ] **Step 1: Add the alias RED matrix**

  Add a single table-driven fixture with exact mutation IDs:

  ```text
  pre-live-lea-reload:
      lea edi,[esp-4]; ... protected call ... mov eax,[edi]
  pre-live-global-publication:
      lea edi,[esp-4]; mov [global],edi; ... protected call
  pre-live-helper-return:
      call helper_returning_lea_esp_minus_4; mov edi,eax; ...; mov eax,[edi]
  call-return-top-base:
      call unresolved_owned-shape; ...; mov eax,[eax]
  ret-eax-alias:
      lea eax,[esp-4]; ret
  ret-ebx-alias:
      lea ebx,[esp-4]; ret
  caller-owned-spill:
      lea eax,[esp-4]; mov [esp+arg_offset],eax
  call-visible-spill:
      lea eax,[esp-4]; mov [esp],eax; call helper
  private-spill-control:
      sub esp,4; lea eax,[esp]; mov [esp],eax; mov ecx,[esp];
      xor ecx,ecx; mov [esp],ecx; add esp,4; ret
  ```

  Hostiles must retain exact call targets and reject scalar quarantine. The private spill/kill control must admit.

- [ ] **Step 2: Run strict RED**

  Run:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_residue_alias'
  ```

  Expected: all hostile assertions fail through false admission or missing alias state; the private control may already pass and is retained as a non-vacuity control.

- [ ] **Step 3: Define the finite alias fact**

  Add:

  ```python
  _PrivateStackAliasOffsets = tuple[int, ...] | None  # None is TOP; () is non-stack

  @dataclass(frozen=True, slots=True)
  class _PrivateStackAliasFact:
      registers: tuple[_PrivateStackAliasOffsets, ...]
      private_spills: tuple[tuple[int, _PrivateStackAliasOffsets], ...]
      escaped: bool
  ```

  Register order is `_REGISTER_FAMILIES`. Cap every finite offset set before insertion. ESP is exact zero at entry. Other incoming registers must be mapped from all exact callers; no closed caller proof means TOP. Full-width kill/immediate becomes `()`. Partial writes preserve TOP/conservatively join.

- [ ] **Step 4: Implement entry-prefix and instruction transfers**

  Track full-width LEA/MOV/copy/constant add/sub and ESP/stack-valued-EBP coordinates. Translate all alias offsets when ESP moves. A spill is private only when `_function_private_stack_coordinate_states` proves the destination currently allocated and not incoming, caller-owned, or in an outgoing call-visible span. Deallocation with a live alias spill rejects.

  An ordinary call makes EAX/ECX/EDX TOP unless an existing interprocedural return-domain proof establishes stack-disjointness; callee-saved aliases remain. Passing or publishing an alias rejects. At RET, any finite/TOP stack alias in any GPR or visible spill rejects.

- [ ] **Step 5: Integrate alias observations with residue overlap**

  At each residue instruction state, join in the prefix alias fact. A non-ESP/EBP memory base with finite stack offsets is converted into effective intervals and audited like an ESP operand. TOP used as a memory base/read/write/address rejects. A prepublished stack address whose possible target later overlaps an exact row or tail also rejects.

  Keep alias state in the enclosing query object or local closure only. Do not add a recovery-wide success cache.

- [ ] **Step 6: Run GREEN and static checks**

  Run the Step 2 command plus Task 2 adjacency, `py_compile`, Ruff check on the two Python files, and `git diff --check`. Require the private spill control and all prior scalar positives to remain green.

---

### Task 4: Context-free interprocedural residue fixed point

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:95606` (`_closed_call_argument_slot_is_consumed`)
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py` around `recursive_incoming_argument_terminated_image`

**Interfaces:**
- Consumes: Task 1 residue lattice, Task 2 exact transfers/currentness, and Task 3 alias facts.
- Produces: a finite worklist keyed by `(function_entry, cursor)` with call subscribers, return facts, reverse caller closure, and uniform-negative-drift widening.

- [ ] **Step 1: Expand the recursive RED matrix**

  Replace the provisional two-case `recursive_incoming_argument_terminated_image` test with exact named mutations:

  ```text
  safe-self-terminal                 expected True
  immediate-caller-reload            expected False
  later-depth-caller-reload          expected False
  second-hostile-caller              expected False
  safe-mutual-terminal               expected True
  hostile-mutual-exit                expected False
  forward-loop-safe                  expected True
  forward-loop-observes              expected False
  positive-drift                     expected False
  mixed-drift                        expected False
  bounded-index-one-overlap          expected False
  ebp-negative-reload                expected False
  unbounded-index                    expected False
  segment-override                   expected False
  non-affine-esp                     expected False
  limit-plus-one                     expected False
  guaranteed-multi-address-overwrite expected True
  one-address-overwrite              expected False
  ```

  Each case asserts exact direct targets, recovered raw successors, the trusted terminal import tuple where present, and non-vacuous Task 1--4 prerequisites before checking `_closed_call_argument_slot_is_consumed` and `_private_stack_store_is_scalar_quarantined`.

- [ ] **Step 2: Record strict RED**

  Run:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_recursive_residue'
  ```

  Expected: `safe-self-terminal`, `safe-mutual-terminal`, `forward-loop-safe`, and guaranteed-overwrite fail only at final non-null/true assertions. Every hostile already rejects or remains marked xfail only until the exact production slice that closes it; do not weaken a hostile to obtain RED.

- [ ] **Step 3: Replace concrete continuations with tabulation**

  Store joined instruction facts in:

  ```python
  states: dict[
      tuple[int, int],
      tuple[_PrivateStackResidueFact, _PrivateStackAliasFact],
  ]
  subscribers: dict[
      int,
      set[tuple[int, int]],  # target -> (caller function, return cursor)
  ]
  return_facts: dict[
      int,
      tuple[_PrivateStackResidueFact, _PrivateStackAliasFact],
  ]
  ```

  At a direct owned call, audit explicit operands, apply CALL implicit transfer, add the subscriber before materializing the callee input, and join the callee entry. At every callee RET, audit `[0,4)`, apply `-4-cleanup`, join the result into every registered caller return cursor, and reprocess new subscribers against existing return facts. Complete root reverse-caller enumeration adds all exact call sites even if not encountered forward.

  Charge the worklist limit before adding a new state/subscriber/return fact. Raw successor domains must equal `_summary_successors` before any edge is enqueued.

  Preserve raw caller/RET nodes for provenance, but canonicalize their exact
  immutable mapping inputs before charging or taking the subscriber-by-return
  product. The subscriber key contains the caller function/return cursor,
  exact caller-base alias fact, transported escape demand, and active
  formatter/stream authority. The return key contains the callee identity,
  exact returned alias fact, and exact callee-entry alias fact. Connect and
  charge each distinct key once. Never merge different bases, demands,
  authorities, returned facts, or entry facts, and never truncate by count.

- [ ] **Step 3a: Close exact pre-root ABI boundaries exposed by retail**

  Add a strict RED using `cw_exception_image()` that requires `_function_is_proven_no_return(...)` to accept a function whose sole reachable exit is the already recovered registered `indirect-jump-cw-exception-continuation`, while the existing incomplete-context-restore mutation remains false. Implement one edge-kind-specific terminal predicate; do not accept arbitrary cross-function or unresolved indirect jumps.

  Add a strict RED for a direct one-jump ordinal-import thunk with two closed callers that each push one exact argument and pop it after return. Require private stack coordinate recovery to remain exact. Add one-fact hostiles for a caller with missing/mixed cleanup and an extra raw reference. Infer zero callee cleanup only when the thunk is terminal, the raw direct-call domain is closed, and all callers prove the same exact caller-cleaned arity. This compatibility proof is entry-prefix authority only and must not weaken live-residue import rejection.

  Extend that RED through the entry-prefix alias tabulator: one caller must invoke the certified thunk and then call a root whose protected inner argument is exactly overwritten. The positive remains true; a paired caller that passes a precomputed pointer to the future protected stack coordinate as the thunk argument remains false. At the certified boundary require every exact argument word to be non-alias, retain callee-saved aliases/private spills, set caller-clobbered `EAX`/`ECX`/`EDX` to TOP, and continue in the caller without entering the one-JMP thunk. Do not reuse this transfer after a protected residue becomes live.

  Add a canonical-frame demand RED: ESP and a proven frame-valued EBP retain exact incoming-slot uses, while EBP overwritten from a scalar register before an indexed dereference contributes no caller-spill demand. Require the existing inherited-EBP all-path seal before applying this projection. An indexed access through a still-canonical ESP/EBP or a read of inherited EBP before replacement remains false.

  Add duplicate-coordinate mapping REDs. Two aligned source spill rows mapping to the same callee coordinate must produce one key with the unioned finite value; more than 64 values at that key widens only that value to TOP. Enforce `len(unique_spill_coordinates) <= 64` after the merge, never the transient projected-row count.

  Add a strict low-`max_summary_iterations` RED in which eight raw RET nodes
  expose one identical semantic return effect under distinct private-stack
  coordinates. The query must stay true without raising the limit. Pair it
  with hostiles whose returned alias fact or caller mapping input differs, and
  retain the existing return-alias publication hostiles, so canonicalization
  cannot erase a distinct escape.

  Add a low-`max_contexts_per_entry` RED that calls the exact audited forward
  `memcpy` body three times with distinct stack source/destination coordinates
  before the protected call. Summarize only its entry-prefix alias effect:
  require the exact reachable body bytes (including callee-save operands and
  return protocol), singleton edge/three stack arguments, finite-value or
  bounded-unsigned scalar length, and finite aliases; return the destination
  alias in `EAX`/`EDX`, preserve
  callee-saved aliases/spills, and scalarize `ECX`. A one-fact body mutation
  or callee-save operand mutation must still exhaust the deliberately low cap,
  and publishing a destination
  equal to the future protected word must reject. Decline the summary when a
  cyclic 32-bit source range may contain a tracked alias-bearing private word;
  once the exact body is recognized, reject instead of falling back to the
  generic callee proof. Include a wraparound hostile that kills the original
  source word after the copy so acceptance cannot come from stale-source
  rejection. Do not use the summary after residue becomes live. Count the
  classifier calls: one fresh query must classify each candidate target at
  most once, with no cross-query cache. Add a register-held length=4 positive
  and memoize its upper bound per call site only within that query.

  Add a distinct caller-bound scalar-format continuation RED around the
  existing audited `sprintf`/`vsnprintf` body chain. Exact retail diagnosis must
  remain part of the RED record: the direct writer authority has no synchronous
  stream authority and reaches the engine only from the bounded formatting
  wrapper; it must not borrow the unrelated stream-wrapper format guard.

  The positive fixture uses a private allocated output buffer, one immutable
  format containing ordered plain `%d`, `%s`, and `%s` conversions, a finite
  immutable domain for both string arguments, and a null-or-empty local select
  whose complete branches rejoin before the push. Require an exact maximum
  output including NUL that remains within the allocation. One-fact hostiles
  cover `%n`, `%p`, `%ls`, flags/width/precision, reordered or missing pushes,
  mutable/unterminated/unknown strings, an unguarded null string, open or extra
  call targets, callback/body mutation, arithmetic wrap, nonallocated output,
  exact-fit-plus-one, and a partial alias-bearing word at the output boundary.
  Add a positive whose scalar output fully overwrites an alias-bearing local
  word and assert that row is killed, plus a partial-overwrite case that retains
  only demonstrably untouched bytes or rejects if the current alias fact cannot
  represent the remainder exactly.

  Implement the format parser and immutable-string measurement as pure bounded
  helpers. At the exact direct call boundary, read every ordered conversion
  argument from the current caller, require the already audited body/edge/return
  chain, prove every stack destination alternative currently allocated, apply
  the scalar overwrite to the alias fact, preserve callee-saved aliases and
  spills outside the range, project escapes, and rejoin the exact caller
  continuation. Set only the audited integer return in `EAX` to scalar;
  `ECX` and `EDX` remain TOP under cdecl. Do not descend into the
  formatter, relax generic `memcpy`, reuse the unrelated wrapper authority, or
  use this summary after residue is live. Memoize only immutable per-call facts
  inside the fresh query and require ordinary fail-closed fallback for every
  declined case.

  Add the next retail-exposed `%s` domain as a separate strict RED for a closed
  registered-record table. Retail diagnosis established that the selected
  pointer at the blocker is not loader-backed: it is the name field of one of
  16 zero-filled, 12-byte records, and one owned registration helper writes the
  name/key/payload triple. Prove the registration helper's bounded empty-slot
  search, exact ordered triple write, nonzero finite key domain, complete
  callsite inventory, and finite immutable name-argument domain. Separately
  prove the reader's bounded index, exact stride, requested-key/selected-key
  equality, nonzero key, and same-record name load. Reconcile complete
  decoded/raw/provisional incoming writes for all three fields before issuing
  the `%s` length domain. Hostiles change one writer field/source/order/width,
  admit a zero key or mutable name, add a writer/callsite, detach the reader
  key guard, change the counter bound/branch/stride, or load a different
  record. A merely bounded index or an assumed immutable table is explicitly
  insufficient authority.

  Add a nested return-offset RED for a restored scalar counter whose exact DEC/TEST recurrence otherwise grows one relative-pointer value per iteration, plus hostiles that copy the counter to EAX, use it as a memory base, or pass it to an observing callee. Collapse that taint only after a complete owned-suffix audit proves scalar-only uses, exact nonobserving callees, and a kill before every reachable RET. Retain the existing decrement-after-collapsed-positive hostile unchanged.

  Add a sealed context-save RED with one positive and one-fact interior-reference,
  malformed-save, returning-restore, and wrong-residue-target hostiles. Admit the
  continuation only when the exact 24-byte context has one current relocation
  to the already audited save body and every remaining owned or provisional
  reference is an adjacent exact nonreturning restore. Apply only the exact
  scalar `EAX`/`ECX` result and cache the classification inside one query.

  Add an exact named-stdcall survivor RED: `GlobalFree` preserves an incoming
  callee-saved EDI mask, kills an incoming caller-clobbered EDX mask, while an
  unknown name and wrong pushed arity reject. Add the same preservation/kill
  pair for the exact publication contracts `EnterCriticalSection` and
  `LeaveCriticalSection`, which deliberately remain outside the generic named
  stdcall list. Use these results only to omit a wholly parametric incoming GPR
  from alias relevance. Never summarize ESP and never turn either ABI fact into
  live-residue import authority.

- [ ] **Step 4: Implement recurrence-shape widening**

  Before an instruction-state join would add another shifted row family, group rows uniquely by `(mask, correlations, pairwise-relative-layout)`. A repeated family may widen only when every moving row has the same `delta < 0` and all other rows are stationary. Convert the moving bytes from both observations into `Tail(max_live_byte)` and retain stationary rows. Apply the identical rule at callee entry, return-fact, and caller-suffix joins.

  Ambiguous duplicate signatures, mixed nonzero deltas, positive/zero drift, correlation mismatch, or more than 64 pre-widen rows rejects. A tail joins with `max`; branch-local shrink never overwrites a larger joined bound.

- [ ] **Step 5: Enforce terminal and all-path closure**

  The graph succeeds only when every reachable transfer is locally free of observation/escape and the connected live-fact component has at least one audited empty-fact or exact trusted ExitProcess witness. A divergent branch with no observation is safe under this partial-correctness property; termination is not authority. A repeated SCC without any return/terminal witness is false. Owned no-return bodies are traversed; `_call_is_proven_no_return` does not skip them. Unowned calls reject with any live fact.

- [ ] **Step 6: Run the exact recursive matrix and adjacency**

  Run the Step 2 selection and:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_scalar or private_stack_residue or noescape_scalar or partial_return or session_capability_seal'
  ```

  Expected: all positives/hostiles green, no limit increase, and the focused runtime remains under 120 seconds.

- [ ] **Step 7: Obtain independent implementation review**

  Review exact-row overlap, alias currentness, recurrence correspondence, tail joins, subscriber return rebasing, raw successor equality, terminal identity, and cap charging. Any concrete Critical/Important finding returns to strict RED before retail validation.

---

### Task 5: Exact retail, root replay, and durable handoff

**Current exact-retail boundary (2026-08-15 14:10 PDT):** the context diagnostic
at formatter callback `0x40395d` is complete. The generic alias lattice widens
the reverse-helper result at exactly 65 enumerated positions, but the existing
independent reverse-helper proof certifies the same return as `("buffer",)`.
A strict seven-case TDD cycle therefore adds only an exact positive-literal
count origin to the existing path-sensitive end/count interpreter; it does not
change the generic alias cap, accept TOP directly, weaken dynamic counts, add a
callback/address allowlist, or raise a semantic limit. The 29-case local
regression slice and static checks are green. The authoritative call-slot replay
is running restart-safe in detached tmux directory
`20260815-literal-count-green-tmux`; no root is accepted until its completed
semantic row is `result=True`.

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Create: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`
- Modify: `.superpowers/sdd/2026-07-12-retail-pcode-proof/outlook-ledger.md`

**Interfaces:**
- Consumes: completed/review-clean Tasks 1--4.
- Produces: exact generic closure at retail `0x4439ae`, preserved protected push `0x44364a`, and a timed publication-root `0x435620` outcome.

- [ ] **Step 1: Run exact narrow retail queries**

  Run the existing pinned diagnostic without changing its authority:

  ```bash
  python build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
    --scan-owned-blocks \
    --private-stack-scalar-quarantine 0x4439ae 0x443770

  python build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
    --scan-owned-blocks \
    --closed-scalar-push 0x44364a 0x4434e0 \
    '0x57fd78,0x57fd7c,0x57fd80,0x57fd84,0x57fd88,0x57fd8c,0x57fd90,0x57fd94,0x57fd98,0x57fd9c,0x57fda0,0x57fda4,0x57fda8,0x57fdac,0x57fdb0,0x57fdb4,0x57fdb8,0x57fdbc,0x57fdc0,0x57fdc4,0x57fdc8,0x57fdcc,0x57fdd0,0x57fdd4,0x57fdd8,0x57fddc,0x57fde0,0x57fde4,0x57fde8,0x57fdec,0x57fdf0,0x57fdf4'
  ```

  Require both results true. Record the exact recurrence shape, tail bound, forward SCC members, terminal import tuple, iteration high-water marks, hydration time, wall time, and RSS. A retail-only code branch or raised limit is a fail-closed stop.

- [ ] **Step 2: Run focused/full-module/static gates**

  Run:

  ```bash
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py \
    -k 'private_stack_scalar or private_stack_residue or noescape_scalar or partial_return or partial_register or session_capability_seal or narrow_scalar_argument or format or writer or stream'
  python -m pytest -q tools/melee-agent/tests/test_retro_x86_cfg.py
  python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
  git diff --check
  ```

  Scan added production lines for retail addresses, hashes, compiler markers, and allowlists. Compare test collection to the expected named recursive-residue and formatter-protocol IDs so `-k` cannot silently deselect a required hostile.

- [ ] **Step 3: Run the timed authoritative root replay**

  After Step 2 is green, run the exact root command under `/usr/bin/time -l`
  in a fresh detached tmux directory:

  ```bash
  python -u build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
    --scan-owned-blocks \
    --task4-publication-certificate \
    --task4-publication-root 0x435620 \
    --no-semantic-trace
  ```

  All four arguments are mandatory: `--task4-publication-root` only filters
  the certificate branch and is a no-op without
  `--task4-publication-certificate`; `--scan-owned-blocks` binds the hydrated
  ownership inventory. Accept only exactly one output row matching
  `task4-publication-certificate;root=0x435620;...;result=True;stages=...`.
  Wait quietly for 15 minutes before polling unless the process completes
  earlier.

  If the root remains false, extract only its terminal named stage/reject reason, update the outlook ledger, and diagnose the next generic boundary. Do not treat progress past `0x4439ae` as root acceptance.

- [ ] **Step 4: Append durable evidence**

  Record RED/GREEN commands and counts, exact-retail facts, timing/RSS, scope scan, reviewer verdict, and root replay result in the active Task 8 report and the 12-hour outlook ledger. Do not add ignored diagnostic logs to git.

- [ ] **Step 5: Commit and push**

  Stage only the two Python files and tracked design/plan/report/ledger files. Verify the staged diff independently:

  ```bash
  git diff --cached --check
  git diff --cached --stat
  git status --short
  ```

  Commit with a scoped `mwcc-retro` message and push `codex/issue-1240-retail-pcode-proof` to `origin`. Then continue the remaining Task 8 path: independent `0x435a8c`, immutable run1/run2 equality, parent promotion/merge, installed replay, issue resolution, and queue refresh.
