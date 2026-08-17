# Formatter Writer Copy Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve one exact formatter source/count certificate across the
engine-to-bounded-writer edge so the writer's unique memcpy can be audited
without weakening generic alias or residue rules.

**Architecture:** Add a frozen query-local authority that is minted only from
an exact engine callback edge after the existing source/count proof succeeds.
Put it in alias-context identity, validate and consume it at the selected
writer's unique memcpy, and restore only the caller's preexisting callback
partition on return.

**Tech Stack:** Python 3.11, Capstone x86 detail API, pytest, Ruff, Git.

## Global Constraints

- Modify only `tools/mwcc_retro/x86_cfg.py`,
  `tools/melee-agent/tests/test_retro_x86_cfg.py`, and the two design/plan
  documents for this repair.
- Do not split `x86_cfg.py` during this proof-currentness repair; record file
  decomposition as post-#1240 maintenance.
- Add no retail address, body hash, callback allowlist, persistent semantic
  cache, or generic unknown-length memcpy exemption.
- Every new authority is immutable, query-local, context-keyed, source-bound,
  and fail closed on ambiguity or limits.
- Preserve all existing exact memcpy, raw-CFG, argument-order, stack-coordinate,
  tracked-spill, escape-demand, and callback-target checks.
- Do not run the four-hour retail query until focused, adjacent, full-module,
  static, and independent-review gates are green.
- Keep `.agents/`, `.coverage`, `.pi/`, and `tools/melee-agent/uv.lock`
  unstaged and byte-preserved.

---

### Task 1: Capture strict RED for engine-edge issuance

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:9099-9164`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:49490-50240`

**Interfaces:**
- Consumes: `_FormatCallbackAuthority`, `_AuditedFormatCursorProtocol`,
  `_PrivateStackAliasFact`, `_audited_format_buffer_end_count`, and
  `_audited_format_writer_callback`.
- Produces: fixture `format_writer_copy_authority_image(tmp_path, *, mutation)`
  and the exact test ID family `private_stack_format_writer_copy_authority`.

- [ ] **Step 1: Extend the exact bounded-writer fixture**

Add `wrong-copy-source` to `audited_format_size_argument_image`.  Change only
the source push at the callback's unique copy call while retaining the exact
memcpy body and count push:

```python
elif mutation == "wrong-copy-source":
    callback_bytes[0x2B] = 0x52  # push ecx -> push edx
```

Assert the changed instruction remains one full-width register PUSH, the copy
target is unchanged, and `_audited_format_writer_callback(callback)` is false.
This catches an issuer or consumer that binds only the writer address.

- [ ] **Step 2: Add a compact engine/writer authority fixture**

Create `format_writer_copy_authority_image` by placing these three real
components in one `load_large_cfg_program` image:

1. the dynamic end-minus-source engine fragment from
   `test_format_buffer_dynamic_count_is_exact_end_minus_pointer` at
   `0x00401080`;
2. the exact 26-instruction writer bytes from
   `audited_format_size_argument_image` at `engine + 0x100`; and
3. the exact memcpy bytes from that fixture at `engine + 0x180`.

Return a facts dictionary containing literal addresses for `engine`,
`callback_call`, `writer`, `copy_call`, `memcpy`, `buffer_base`, and the
hand-derived writer source aliases.  Support exactly these mutations:

```python
{
    None,
    "add-count",
    "wrong-clamp-operand",
    "wrong-copy-count",
    "wrong-copy-source",
    "excluded-target",
}
```

Use the existing one-byte encodings:

```python
if mutation == "add-count":
    engine_bytes[count_sub_offset] = 0x01  # sub -> add
elif mutation == "wrong-clamp-operand":
    writer_bytes[0x15] = 0xD8
elif mutation == "wrong-copy-count":
    writer_bytes[0x2A] = 0x52
elif mutation == "wrong-copy-source":
    writer_bytes[0x2B] = 0x52
```

The fixture may seed only the recovered indirect callback target row needed
to model the synthetic callback edge.  It must not monkeypatch the source/count
proof or writer recognizer.

- [ ] **Step 3: Add the issuance behavior test**

Add a parameterized test whose production mutation target is “minting an
authority without exact engine count, target, writer, or source evidence”:

```python
@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (None, True),
        ("add-count", False),
        ("wrong-clamp-operand", False),
        ("wrong-copy-count", False),
        ("wrong-copy-source", False),
        ("excluded-target", False),
    ),
    ids=(
        "private_stack_format_writer_copy_authority-positive",
        "private_stack_format_writer_copy_authority-add-count",
        "private_stack_format_writer_copy_authority-wrong-clamp-operand",
        "private_stack_format_writer_copy_authority-wrong-copy-count",
        "private_stack_format_writer_copy_authority-wrong-copy-source",
        "private_stack_format_writer_copy_authority-excluded-target",
    ),
)
def test_private_stack_format_writer_copy_authority_requires_exact_edge(
    tmp_path,
    monkeypatch,
    mutation,
    expected,
):
    image, facts = format_writer_copy_authority_image(
        tmp_path,
        mutation=mutation,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    protocol = facts["protocol"]
    monkeypatch.setattr(
        recovery,
        "_unique_audited_format_cursor_protocol_for_writer",
        lambda engine, writer: (
            protocol
            if (engine, writer) == (facts["engine"], facts["writer"])
            else None
        ),
        raising=False,
    )
    recovery.call_targets_by_source[facts["callback_call"]] = {
        facts["writer"]
    }
    current = _FormatCallbackAuthority(
        facts["engine"],
        (
            ()
            if mutation == "excluded-target"
            else (facts["writer"],)
        ),
    )

    result = recovery._audited_format_writer_copy_authority(
        facts["engine"],
        facts["callback_call"],
        facts["writer"],
        facts["engine_aliases"],
        facts["writer_initial_aliases"],
        current,
    )

    assert (result is not None) is expected
    if result is not None:
        assert result.engine == facts["engine"]
        assert result.callback_call == facts["callback_call"]
        assert result.writer == facts["writer"]
        assert result.source_aliases == facts["writer_source_aliases"]
        assert result.length_upper == protocol.cursor_extent + 1
```

The protocol recognizer is the only test double because the retail engine
recognizer is a 494-instruction component.  The real engine-side range proof,
writer recognizer, call ownership, source mapping, and mutation bytes remain
active.

- [ ] **Step 4: Run RED and record the boundary**

Run:

```bash
cd tools/melee-agent
uv run pytest tests/test_retro_x86_cfg.py \
  -k private_stack_format_writer_copy_authority -vv
```

Expected on unchanged production: the selected positive fails because
`_audited_format_writer_copy_authority` does not exist; all nonvacuity and
mutation assertions before that call pass.  Record the command and exact
failure in `task-8-report.md`; do not change production yet.

---

### Task 2: Implement the authority schema and issuer

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:140-170`
- Modify: `tools/mwcc_retro/x86_cfg.py:104580-104690`
- Modify: `tools/mwcc_retro/x86_cfg.py:107120-107320`

**Interfaces:**
- Consumes: the exact protocol and alias facts from Task 1.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class _FormatWriterCopyAuthority:
    engine: int
    callback_call: int
    writer: int
    source_aliases: tuple[_PrivateStackAliasCoordinate, ...]
    length_upper: int
```

Add `_unique_audited_format_cursor_protocol_for_writer(self, engine: int,
writer: int) -> _AuditedFormatCursorProtocol | None` and
`_audited_format_writer_copy_authority(self, engine: int, callback_call: int,
writer: int, engine_aliases: _PrivateStackAliasFact,
writer_initial_aliases: _PrivateStackAliasFact, callback_authority:
_FormatCallbackAuthority | None) -> _FormatWriterCopyAuthority | None`.

- [ ] **Step 1: Add the frozen schema**

Place `_FormatWriterCopyAuthority` immediately after
`_FormatCallbackAuthority`.  Do not add defaults.  Reject malformed facts at
the first consumer rather than normalizing them.

- [ ] **Step 2: Add unique protocol discovery**

Implement the address-independent discovery rule:

```python
if not (
    engine in self.function_addresses
    and writer in self.function_addresses
    and self._audited_format_writer_callback(writer)
    and self._incoming_call_domain_is_closed(engine)
):
    return None

candidates = set()
for source in sorted(self.direct_call_sources_by_target.get(engine, ())):
    caller = self._registrar_function_entry(source)
    if caller is None:
        return None
    callback_targets = self._finite_format_callback_targets_for_engine_call(
        source,
        caller,
        engine,
    )
    stream_targets = (
        self._finite_synchronous_stream_callback_targets_for_call_argument(
            source,
            caller,
            1,
        )
    )
    if callback_targets is None:
        return None
    if stream_targets is None:
        continue
    for wrapper in callback_targets:
        if wrapper == writer:
            continue
        protocol = self._audited_format_cursor_protocol(
            engine,
            wrapper,
            frozenset(stream_targets),
        )
        if protocol is not None:
            candidates.add(protocol)
return next(iter(candidates)) if len(candidates) == 1 else None
```

Keep any memo for this method inside the outer call-slot query and key it by
`(engine, writer)`; do not add an object-global cache.

- [ ] **Step 3: Mint the authority at one exact edge**

The issuer must:

1. require `callback_authority.engine == engine` and membership of `writer`;
2. require the exact recovered target set at `callback_call` contains `writer`;
3. derive the engine call SP coordinate and exact source argument at index 1;
4. read the nonempty finite source alias from `engine_aliases.private_spills`;
5. require `_audited_format_buffer_end_count` for that exact source value;
6. derive the writer entry SP coordinate and its argument-1 source alias from
   `writer_initial_aliases`;
7. require a nonempty finite mapped source tuple with at most 64 coordinates;
8. compute `length_upper = protocol.cursor_extent + 1` and require
   `0 < length_upper <= 0xFFFF_FFFF`; and
9. return the exact frozen row.

Any missing row, ambiguous protocol, TOP alias, scalar source, mapping drift,
or `AnalysisLimitError` returns `None`.

- [ ] **Step 4: Run the issuer GREEN**

Run the Task 1 command.  Expected: all six IDs pass.  Then run:

```bash
uv run pytest tests/test_retro_x86_cfg.py \
  -k 'format_buffer_dynamic_count or capability_push_accepts_only_audited_format_size_argument' \
  -vv
```

Expected: all existing source/count and writer mutations remain green.

---

### Task 3: Capture RED and implement writer-context consumption

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:48450-48560`
- Modify: `tools/mwcc_retro/x86_cfg.py:104500-109180`

**Interfaces:**
- Consumes: `_FormatWriterCopyAuthority` from Task 2.
- Produces: context plumbing and a source-bound conservative memcpy length.

- [ ] **Step 1: Add direct consumer hostiles before production plumbing**

Add a focused test whose production mutation target is “using an authority in
the wrong writer, at the wrong copy, or for a different source”:

```python
@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (None, 0x201),
        ("wrong-writer", None),
        ("wrong-call", None),
        ("wrong-source", None),
        ("wrong-copy-count", None),
    ),
    ids=(
        "private_stack_format_writer_copy_consumer-positive",
        "private_stack_format_writer_copy_consumer-wrong-writer",
        "private_stack_format_writer_copy_consumer-wrong-call",
        "private_stack_format_writer_copy_consumer-wrong-source",
        "private_stack_format_writer_copy_consumer-wrong-copy-count",
    ),
)
def test_private_stack_format_writer_copy_authority_is_source_bound(
    tmp_path,
    mutation,
    expected,
):
    image, _caller, _push, callback = audited_format_size_argument_image(
        tmp_path,
        mutation=(
            "wrong-copy-count"
            if mutation == "wrong-copy-count"
            else None
        ),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_call = callback + 0x2D
    copy = callback + 0x80
    source_aliases = ((0, 0x40),)
    authority = x86_cfg_module._FormatWriterCopyAuthority(
        engine=callback - 0x100,
        callback_call=callback - 0x80,
        writer=(callback + 1 if mutation == "wrong-writer" else callback),
        source_aliases=(
            ((0, 0x44),) if mutation == "wrong-source" else source_aliases
        ),
        length_upper=0x201,
    )
    result = recovery._format_writer_copy_length_upper_for_memcpy(
        callback,
        copy_call + (1 if mutation == "wrong-call" else 0),
        copy,
        source_aliases,
        authority,
    )
    assert result == expected
```

Construct the authority with literal fields and use the exact writer/memcpy
fixture.  Mutate one input at a time; do not compute the expected value with a
production helper.

- [ ] **Step 2: Verify the consumer RED**

Run:

```bash
uv run pytest tests/test_retro_x86_cfg.py \
  -k private_stack_format_writer_copy_consumer -vv
```

Expected: the positive fails because the consumer is absent; fixture and
hostile preconditions pass.

- [ ] **Step 3: Add the exact consumer**

Implement:

Add `_format_writer_copy_length_upper_for_memcpy(self, caller_entry: int,
call_source: int, target: int, source_aliases:
tuple[_PrivateStackAliasCoordinate, ...], authority:
_FormatWriterCopyAuthority | None) -> int | None`.

Require schema ranges, `authority.writer == caller_entry`, exact source tuple,
`_audited_format_writer_callback(caller_entry)`, exactly one direct call in
the writer, and exact equality of that call's address/target with
`call_source`/`target`.  Return only `authority.length_upper`.

- [ ] **Step 4: Thread the authority through alias contexts**

Add an optional `format_writer_copy_authority` parameter to
`ensure_alias_context`; include it in `alias_context_keys`; store it in a
query-local dictionary keyed by context ID.  Validate that its writer equals
the context owner and that its fields are canonical.

When processing an engine callback target:

1. calculate `target_initial_alias` with the existing exact mapping;
2. mint the writer authority from current engine aliases, target initial
   aliases, and `context_format_callback_authority`;
3. pass it only into the selected target context; and
4. pass `None` for all ordinary targets.

Do not add the writer authority to `_PrivateStackAliasSubscriberEffect`.
Subscriber return mapping must restore the caller's existing engine callback
authority and discard the callee-only writer authority.

- [ ] **Step 5: Consume it in `memcpy_alias_continuation`**

Add the authority parameter.  Preserve the current finite and interval length
routes.  Only when both are absent may the new consumer supply `length_upper`:

```python
if length is None:
    length = self._format_writer_copy_length_upper_for_memcpy(
        caller_entry,
        call_source,
        target,
        source,
        writer_copy_authority,
    )
```

Run the existing tracked-spill overlap block unchanged with that upper bound.
On the special memcpy continuation, call `ensure_alias_context` with writer
authority `None`, consuming it.  All other continuation paths retain the
current value only while still inside the writer before the unique copy.

- [ ] **Step 6: Run focused GREEN and lifetime controls**

Run:

```bash
uv run pytest tests/test_retro_x86_cfg.py \
  -k 'private_stack_format_writer_copy_authority or private_stack_format_writer_copy_consumer' \
  -vv
uv run pytest tests/test_retro_x86_cfg.py \
  -k 'private_stack_alias or format_callback or format_buffer or audited_format' \
  -q
```

Expected: both new matrices and all existing authority/lifetime partitions
pass.  Add a direct post-engine invocation control if the second command
reveals no existing return-lifetime case; it must receive no writer authority
and reject an otherwise identical unknown-length stack source.

---

### Task 4: Verify, review, commit, and relaunch

**Files:**
- Modify: `.superpowers/sdd/2026-08-06-private-page-arena-invariant/task-8-report.md`
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: the complete GREEN repair.
- Produces: one reviewed semantic commit and a restart-safe retail replay.

- [ ] **Step 1: Run static and full-module gates**

Run from the worktree root:

```bash
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
cd tools/melee-agent
uv run pytest tests/test_retro_x86_cfg.py -q
```

Expected: zero static errors and the complete x86 module passes.  Do not run
`ruff format`.

- [ ] **Step 2: Run exact-retail structural mini-query**

Use `hydrate-cfg-query.py` with the retained exact raw CFG to assert:

- `_audited_format_writer_callback(0x403aa0) is True`;
- the unique cursor protocol is nonnull with `cursor_extent == 0x200`;
- `_audited_format_buffer_end_count` is true at `0x40395d` and `0x4039b0`;
- the writer copy call is `0x403acd -> 0x404c30`; and
- no analysis limit is reported.

This is diagnostic evidence only; it does not replace the call-slot replay.

- [ ] **Step 3: Request independent review**

Give the reviewer the design, plan, complete production/test diff, strict RED
record, focused/full/static outputs, and mini-query output.  Require an
explicit Critical/Important/Minor verdict on authority issuance, source
binding, callback partitioning, tracked-spill overlap, context identity,
return lifetime, and cache currentness.  Resolve every Critical or Important
finding with a fresh RED/GREEN cycle.

- [ ] **Step 4: Commit and push the reviewed repair**

Stage exactly the production file, test file, design correction, plan, and
ignored report only if tracked.  Verify staged scope, then:

```bash
git commit -m "fix(mwcc-retro): retain formatter copy authority"
git push origin codex/issue-1240-retail-pcode-proof
```

Record the commit, parent, scope, tests, mini-query, reviewer verdict, and
protected-untracked inventory in `task-8-report.md`.

- [ ] **Step 5: Launch one restart-safe exact call-slot replay**

Create a unique run directory and wrapper derived from the last reviewed
call-slot invocation.  Pin the new HEAD, wrapper/helper hashes, compiler hash,
and exact output schema.  Launch under a unique tmux session; write started,
finished, exit, result, wall/RSS, stdout/stderr hashes, and terminal marker
atomically.  Check it only at meaningful boundaries, using long waits.

If the call-slot result is positive, build a fresh reviewed handoff chain for
root `0x435620`, companion `0x435a8c`, and the manual pre-v6 boundary.  If it
fails, stop at the first new semantic rejection and return to systematic
diagnosis; do not let downstream handoffs advance.
