# Private-Page Arena Invariant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Reviewed amendment:** 2026-08-07

**Goal:** Certify the exact page-ring and block-arena metadata accesses reached
through a closed private allocator without granting generic private-heap
dereference authority.

**Architecture:** Keep `_PrivateHeapAllocatorContract` as the structural
prerequisite and `_PublicationPrivateHeapEffectClosure` as the induction base.
Discover page-ring roles from those contracts, then close selector, every
initializer-executed helper reused by later arena contexts, a first-class
arena-free/deallocator compound transfer, and structurally admitted resize
invocation contexts with one bounded relational interpreter. Track allocation
and list membership independently, prove nested local postconditions plus
compound restoration boundaries, serialize typed call edges, contextual
invocations, exact triple-keyed spans, the derived induction-substitution set,
and the embedded initializer effects; let `_publication_body_address_domains`
consume only operand-specific arena evidence.

**Tech Stack:** Python 3, Capstone x86 decoding, pytest, Ruff, and the existing
hydrated raw-CFG diagnostic.

## Global Constraints

- Production discovery must not compare a function, call site, image slot, or
  owner against a retail address or owner allowlist.
- A plain `_PublicationPrivateHeapAddressDomain` must remain insufficient for
  every real memory dereference.
- Begin with a non-null `_PrivateHeapAllocatorContract` and the exact existing
  extent/effect witness; do not create a parallel allocator recognizer.
- Treat `_PublicationPrivateHeapEffectClosure` as the sole induction base and
  embed it unchanged in the final invariant. Do not emit an ordinary
  `initialize` transfer.
- Recover layout values and transfer roles from decoded evidence rather than
  symbol names, byte-string identity, or familiar constants used as selectors.
- Keep extent alignment distinct from block alignment. Exact retail integration
  expects `0x1000` and `8`, respectively, but production discovery derives both
  values structurally. They constrain `E` and block arithmetic; do not infer or
  assert that `P` is page-aligned.
- Close every role's incoming invocation domain. An extra caller is admitted
  only as a structurally proved bounded resize context; every other extra
  caller, writer, unknown value/relation, conflicting role, unclassified arena
  operand, or stale dependency fails closed.
- Treat allocation and free-list membership as independent state components.
  Permit `free/unlisted` only at the exact initializer/selector-B2/insert
  transients and `allocated/listed` only inside unlink after bit-2 set and
  before detachment. Resize split returns `allocated/unlisted`; require stable
  state at compound returns, not every instruction.
- Treat split's `0x40408f` and `0x4040a6` block-initializer sites as an ordered
  pair executed in every selector and resize invocation. Both calls receive the
  allocation value copied from input `B` header bit `2`; never classify them as
  mutually exclusive or context-selected sites.
- Derive `induction_substituted_entries` as the exact intersection of helpers
  executed by the initializer effects and helpers active in later arena
  transfers. Retail includes both insert and block initializer. Replay their
  initializer executions only as induction evidence; do not install those
  effect spans as later body authority. Every later execution requires the
  helper's complete arena transfer and triple-keyed spans. Reject any true
  simultaneously installed exact effect/arena key collision.
- Serialize one `arena-free` compound transfer rooted in the closed deallocator
  context. It must bind allocated payload recovery, the `free/unlisted`
  transient, insert/coalescing, optional whole-page ring removal/release, and
  restoration before the deallocator boundary returns.
- Prove private-free's direct small and arena branches mutually exclusive. A
  small payload reaches small-free only; any later arena-free call is a
  separately certified backing-page retirement, not a second interpretation of
  the original payload.
- Use `(function_entry, instruction_address, operand_index)` as the only arena
  span key. Instruction-address inventories and two-component keys are not
  authority.
- Store typed call-edge and contextual invocation rows. Bare integer edge pairs
  are not durable evidence.
- Snapshot canonical function, global-slot, and absolute-reference
  dependencies and replay them before any body consumes a span.
- Extend the existing ignored `--private-heap-extent` diagnostic; do not add a
  new CLI command, helper script, or persistent artifact format.
- Keep exact development queries under two minutes. Do not rerun a full root
  until the local suite and exact mini-query pass.
- Do not weaken protected-slot, mapped-image capability, reference inventory,
  raw-control-flow, or initializer effect checks.

## File Map

- `tools/mwcc_retro/x86_cfg.py`: evidence dataclasses, structural discovery,
  invariant transfer proof, dependency replay, and body-domain integration.
- `tools/melee-agent/tests/test_retro_x86_cfg.py`: synthetic page-arena fixture,
  positive tests, hostile mutations, replay tests, and integration tests.
- `build/diagnostics/task4-repair-exact/hydrate-cfg-query.py`: ignored
  diagnostic output only; extend its existing `--private-heap-extent` branch.
- `docs/superpowers/specs/2026-08-06-private-page-arena-invariant-design.md`:
  reviewed proof contract.
- `docs/superpowers/plans/2026-08-06-private-page-arena-invariant.md`: tracked
  execution checklist and observed validation results.

---

### Task 1: Freeze the Page-Arena Boundary in a Synthetic Fixture

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:3240-4050`

**Interfaces:**
- Consumes: `finalized_handle_arena_image()`,
  `_publication_body_address_domains()`.
- Produces: `PrivatePageArenaFixture`, `private_page_arena_image()`, and a
  retail-shaped, non-vacuous graph whose existing allocator, extent, and
  initializer-effect proofs reach the selector, all mutation roles, and a
  bounded resize context while the current body audit still bottoms at the
  missing inductive witness.

- [ ] **Step 1: Add the fixture interface and exact role graph**

```python
@dataclass(frozen=True, slots=True)
class PrivatePageArenaFixture:
    arena: FinalizedHandleArenaFixture
    page_head_slot: int
    page_provider: int
    large_allocator: int
    page_inserter: int
    page_remover: int
    selector: int
    selector_calls: tuple[int, int]
    block_initializer: int
    block_initializer_calls: tuple[int, int, int]
    splitter: int
    unlinker: int
    block_inserter: int
    coalescers: tuple[int, int]
    arena_free: int
    reallocator: int
    reallocator_calls: tuple[int, ...]


def private_page_arena_image(
    *, mutation: str | None = None
) -> PrivatePageArenaFixture:
    """Return one closed synthetic page ring and block arena."""
```

Extend the existing synthetic private allocator and its actual
`_PublicationPrivateHeapExtentWitness` / `_PublicationPrivateHeapEffectClosure`
producer; do not place a disconnected page-arena image beside it.

The fixture must encode these structural facts rather than merely asserting
them in comments:

- The provider normalizes one extent, obtains the exact factory result, calls
  the retained initializer helper, publishes that same page, and returns it.
- The large allocator alone normalizes the request once as an aligned value
  with a positive floor. A null initial head calls the provider and joins the
  first selector invocation; a non-null head supplies a ring page. Exhaustion
  calls the provider for the second selector invocation. Both invocations
  receive the same normalized request lineage. Successful selection from the
  existing-ring arm rotates that page into the head slot.
- The initializer writes `P+8` largest-free, `P+0xc` as tagged `E`, first block
  `P+0x10`, page-end tag `P+E-8`, boundary tag `B+S-4`, and zero sentinel
  `P+E-4`. Its exact effect execution calls the same block initializer used by
  split and routes the resulting `free/unlisted` initial block through the same
  insert role used by free and resize. Thus both helper entries are in the
  initializer execution closure and later require induction substitution. The
  page publisher alone writes `P+0`/`P+4` ring links.
- The selector walks `B+0xc`, tracks/writes largest-free on exhaustion, proves
  fit and the minimum remainder, calls split before it writes the sentinel from
  `B.next`, then unlinks and returns `B`. No selector or split-local request
  renormalization is allowed.
- Split has selector and resize contexts, and every invocation executes both
  block-initializer sites sequentially. It snapshots input `B` header bit `2`
  and passes that allocation value to both `B` and `B2=B+R`; neither site is a
  context alternative. Selector enters with `free/listed` `B`: the first call
  preserves `B`, the second produces `free/unlisted` `B2`, and split links `B2`
  before returning both blocks `free/listed`. Selector then unlinks `B`, setting
  bit `2` and detaching it to `allocated/unlisted` while covering exact `D`,
  singleton, reciprocal-link, sentinel-head, and `P+8` updates. Resize enters
  with `allocated/unlisted` `B`; both calls preserve that state and returned
  `B2` remains `allocated/unlisted` until insert clears bit `2` and lists it.
  There is no resize `free/unlisted` remainder or selector
  `allocated/listed` helper return.
- The payload begins at `B+8`, overlaying the free block's `+8/+0xc` links.
  Arena free recovers `B` by subtracting the same offset and masks the distinct
  page-pointer flag from `B+4`. Its compound path starts from an
  `allocated/unlisted` payload block; insert clears bit `2` to the bounded
  `free/unlisted` state before it links and coalesces the block. The transfer
  either returns the stable `free/listed` survivor or proves
  the exact whole-page predicate before page-ring removal and release. No
  transient may reach the deallocator return.
- Insert accepts initializer `free/unlisted` or proved arena-free/resize
  `allocated/unlisted`, clears bit `2` before it links the block, then calls
  coalesce-prev and
  coalesce-next. Previous coalescing unlinks current `B` and leaves the
  predecessor as survivor; next coalescing unlinks `N=B+S` and leaves `B` as
  survivor. Largest-free is updated after coalescing.
- A reachable resize driver passes an exact large-allocator payload to the
  reallocator. Its grow path coalesces next before guarded split+insert; its
  shrink path performs guarded split+insert. Both paths must consume every
  `allocated/unlisted` returned `B2` through insert's bit-2 clear and listing
  before returning.
- Private-free classifies a non-null payload once and takes exactly one direct
  branch to small-free or arena-free. The small branch may retire a backing
  arena page through a separate nested arena-free call, but the original
  payload never traverses both direct branches.

The exact fixture constants may mirror retail for integration clarity, but no
production recognizer may use them as selectors.

- [ ] **Step 2: Add the passing boundary regression**

```python
def test_private_page_arena_still_requires_an_inductive_witness():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects, closure, bridge = (
        private_page_arena_publication_inputs(fixture)
    )

    assert contract is not None
    assert extent is not None
    assert effects is not None
    assert fixture.selector in {
        body.function_entry for body in closure.bodies
    }
    assert effects.bounded_spans  # The induction base is real, not a fake bridge.
    assert effects.symbolic_writes  # Layout facts came from that execution.
    assert fixture.reallocator in recovery.function_addresses

    role_callers = {
        target: {
            recovery._registrar_function_entry(address)
            for address in recovery._incoming_call_sites(target)
        }
        for target in (
            fixture.block_initializer,
            fixture.splitter,
            fixture.block_inserter,
            *fixture.coalescers,
        )
    }
    assert fixture.reallocator in role_callers[fixture.splitter]
    assert fixture.reallocator in role_callers[fixture.block_inserter]

    assert recovery._publication_body_address_domains(
        fixture.arena.callback_slot, closure, (bridge,)
    ) is None
```

- [ ] **Step 3: Run the fixture and existing private-heap tests**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_arena_still_requires or publication_body or private_heap'
```

Expected: the new boundary regression and all preexisting selected tests pass.

- [ ] **Step 4: Commit the fixture boundary**

```bash
git add tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "test(mwcc-retro): model private page arena"
```

> **Reviewed correction (2026-08-07):** The first fixture audit found that its
> page-ring graph was disconnected from the existing extent/effect producer,
> while Task 2 assumed unavailable initializer-effect spans for page links and
> one overloaded alignment value. Task 1 remains unchecked until one coherent
> graph replaces those shapes plus the earlier unlink-before-split,
> coalesce-before-insert, always-free split, and selector-local normalization.
> The boundary regression must reach the real selector with a nonempty
> induction base and include the exact resize caller shapes. Task 2 derives
> only initializer layout; Task 3 alone binds publisher page links. Later tasks
> must not compensate for an incomplete fixture.

---

### Task 1A: Retain Exact Initializer Symbolic Writes

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1690-1745`
- Modify: `tools/mwcc_retro/x86_cfg.py:19370-20120`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11850-12050`

**Interfaces:**
- Consumes: the existing bounded interpreter's per-instruction affine memory
  key, value-before/value-after, operation, and immediate mask.
- Produces: `_PublicationPrivateHeapSymbolicWrite` and the canonical
  `_PublicationPrivateHeapEffectClosure.symbolic_writes` tuple.

- [x] **Step 1: Write RED symbolic-write evidence tests**

Use the existing positive effect fixtures to require deterministic rows for
`mov`, `or`, and `and`, including nested function identity, exact
`(instruction_address, operand_index)`, affine destination, width,
value-before/value-after, and immediate. Add hostiles for a stale function
fingerprint, a row outside `executed_instruction_addresses`, duplicate location
keys, malformed affine/value shapes, and an unknown value. Unknown rows remain
serialized but cannot establish a later layout fact.

- [x] **Step 2: Thread rows through the existing interpreter**

Collect rows at the point where `execute_function` already computes the memory
key and write value; merge nested rows exactly like bounded spans, sort by
`(function_entry, instruction_address, operand_index)`, and reject duplicate
location keys. Do not create a second interpreter and do not change generic
bounded-span authorization.

- [x] **Step 3: Run the effect suite and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_heap_effect or private_heap_symbolic_write'
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): retain initializer write evidence"
```

Observed through `d0fe94dc6` and `6f8d7f619`: the exact-write evidence gained
operand-bound bit-operation provenance and a structurally rebound allocator
contract token after adversarial review. The final 16-test provenance review
selection and complete 1,568-test x86-CFG suite passed independently; the
canonical 13-test effect selection, Ruff, `py_compile`, and diff checks were
clean. The exact retail mini-query hydrated in 13.81 seconds, retained
`P | 1`, the `E | 3` then `E & ~7` address chain, and `E - 0x18`, and returned
non-null effects with 30 body domains. Independent final review found no
remaining Critical or Important findings. Task 2 must re-run
`_publication_private_heap_effect_closure_is_current(effects)` at its evidence
consumption boundary before deriving layout facts.

---

### Task 2: Recover the Layout and Bind the Initial Invariant

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1660-1750`
- Modify: `tools/mwcc_retro/x86_cfg.py:18580-20280`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11300-11750`

**Interfaces:**
- Consumes: `_PrivateHeapAllocatorContract`,
  `_PublicationPrivateHeapExtentWitness`, and
  `_PublicationPrivateHeapEffectClosure` from Task 1's single coherent graph.
- Produces: `_PublicationPrivatePageLayout` and
  `_publication_private_page_layout(contract, extent, effects)`.

- [ ] **Step 1: Write the RED positive and hostile layout tests**

```python
def test_private_page_layout_is_derived_from_initializer_effects():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects = private_page_arena_contract(fixture)

    layout = recovery._publication_private_page_layout(contract, extent, effects)

    assert layout is not None
    assert layout.extent_alignment == 0x1000
    assert layout.block_alignment == 8
    assert layout.page_link_offsets is None
    assert layout.page_largest_free_offset == 8
    assert layout.page_extent_offset == 12
    assert layout.first_block_offset == 0x10
    assert layout.page_end_tag_displacement == -8
    assert layout.end_sentinel_displacement == -4
    assert layout.block_header_offset == 0
    assert layout.block_page_flags_offset == 4
    assert layout.block_prev_offset == 8
    assert layout.block_next_offset == 12
    assert layout.block_boundary_tag_displacement == -4
    assert layout.size_flag_mask == 7
    assert layout.minimum_split_remainder is None
```

Add parametrized mutations for a changed extent/size mask, changed sentinel
displacement, missing first-block construction, out-of-range initial boundary
tag, missing `P+8` largest-free initialization, changed block page/flag field,
an initializer effect that omits one layout operand, and an effect/layout token
mismatch. Each hostile must assert a `None` layout result. A page-link write is
deliberately not a Task 2 input: it belongs to the Task 3 publisher proof.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_layout'
```

Expected: FAIL with `_publication_private_page_layout` missing.

- [ ] **Step 3: Add the spec dataclasses and layout recognizer**

Add `_PublicationPrivatePageLayout`, `_PublicationPrivateArenaBlockState`,
`_PublicationPrivateArenaInvocation`,
`_PublicationPrivateArenaStateTransition`,
`_PublicationPrivatePageRingRole`, `_PublicationPrivateArenaCallEdge`,
`_PublicationPrivateBlockArenaRole`, `_PublicationPrivateArenaSpan`,
`_PublicationPrivateArenaTransfer`, `_PublicationPrivateArenaDependency`, and
`_PublicationPrivatePageArenaInvariant` adjacent to the existing publication
evidence. Implement:

```python
def _publication_private_page_layout(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
) -> _PublicationPrivatePageLayout | None:
    """Recover initializer layout from the certified provider/initializer."""
```

Replay contract, extent, and effect fingerprints. Consume the canonical
symbolic-write rows retained by the exact certified provider/initializer
execution together with its operand-keyed effect spans to derive `P+8`
largest-free, `P+0xc` extent/flag word (`E | 3`), first block `P+0x10`, page
end tag `P+E-8`, block boundary tag `B+S-4`, sentinel `P+E-4`, and block
size/page-flags/prev/next fields `+0/+4/+8/+0xc`. Derive extent and block
alignment separately (the exact retail assertions are `0x1000` and `8`);
neither establishes alignment of `P`. Name the recovered low-bit mask
`size_flag_mask`; page-pointer, allocation/list, and previous-allocation flag
semantics are distinct Task 5 evidence and must not be inferred from this one
mask.
Reject duplicate layouts, wrap, or any initializer span outside `[P, P+E)`.
Reject malformed, duplicate, unknown, unexecuted, or unfingerprinted symbolic
write rows rather than reinterpreting familiar decoded bytes independently.
Set `page_link_offsets=None`: exact `P+0`/`P+4` links are not part of the
initializer effect evidence and Task 3 alone may bind them. The split threshold
remains absent until Task 4 binds its unique selector guard, so represent it as
`int | None` and require a non-null value in the final certificate.
The final Task 6 invariant embeds this exact `effects` object as the induction
base; Task 2 does not synthesize an `initialize` transfer.

- [ ] **Step 4: Run layout/effect tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_layout or private_heap_effect or bounded_private_heap'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): recover private page layout"
```

Expected: all selected tests pass before the commit.

---

### Task 3: Prove Page-Ring Membership and Selector Arguments

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:18350-20280`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11300-11900`

**Interfaces:**
- Consumes: allocator contract, extent witness, and recovered layout.
- Produces: an updated `_PublicationPrivatePageLayout` with the publisher's
  link offsets, `_PublicationPrivatePageRingRole`, triple-keyed ring spans,
  contextual selector page/request invocations, and durable insert/remove/
  rotate transfers retained together as immutable
  `_PublicationPrivatePageRingEvidence` from
  `_publication_private_page_ring_role(contract, extent, layout)`.

- [ ] **Step 1: Write the RED role-discovery test**

```python
def test_private_page_ring_proves_both_selector_page_arguments():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects = private_page_arena_contract(fixture)
    layout = recovery._publication_private_page_layout(contract, extent, effects)
    assert layout is not None

    ring_result = recovery._publication_private_page_ring_role(
        contract, extent, layout
    )
    assert ring_result is not None
    ring_evidence = ring_result
    layout = ring_evidence.layout
    ring = ring_evidence.role
    ring_transfers = ring_evidence.transfers
    ring_spans = ring_evidence.spans
    assert layout.page_link_offsets == (0, 4)
    assert ring.head_slot == fixture.page_head_slot
    assert ring.provider_entry == fixture.page_provider
    assert ring.inserter_entry == fixture.page_inserter
    assert set(ring.selector_page_calls) == set(fixture.selector_calls)
    assert ring.selector_request_calls == ring.selector_page_calls
    assert ring.head_writes
    assert ring.ring_link_writes
    assert {row.role for row in ring_transfers} >= {
        "ring-insert", "ring-remove", "ring-rotate"
    }
    selector_invocations = ring.selector_invocations
    assert all(invocation.page_origins for invocation in selector_invocations)
    assert {
        origin
        for invocation in selector_invocations
        for origin in invocation.page_origins
    } == {"provider", "ring"}
    assert ring.remover_call_obligations
    ring_remove = next(
        transfer for transfer in ring_transfers
        if transfer.role == "ring-remove"
    )
    assert ring_remove.invocations == ()
    assert ring_spans
```

Exercise durable removal from a nonempty ring as well as the singleton-to-null
case, and require the recovered transfer inventory to distinguish removal from
head rotation and insertion. The remover must update the exact recovered head
slot and reciprocal link fields; a null head is the only accepted empty-ring
result. Reconcile the remover's complete raw/decoded incoming call domain and
retain every resolved deallocator-owned site as an immutable
`_PublicationPrivateRemovalCallObligation`. These rows are deliberately not
semantic invocations: Task 3 has not proved the payload overlay, page-pointer
flag, or complete typed-writer invariant. Therefore the Task 3 `ring-remove`
transfer has `invocations == ()` and no call fact carries a `ring` page origin.

The ring dataclass keeps `selector_page_calls` distinct from `provider_calls`;
the implementation must populate and replay both inventories. A selector call
site may be a control-flow join and therefore have `("provider", "ring")` as
its page-origin subset. Require every site to have a nonempty subset and the
union across sites to contain both origins; do not require one origin per site.
The request argument at every selector site must have the identical normalized
lineage from the large allocator. Because these rows describe page/request
calls before a block is selected, their input `block_state` is `none/none`;
Task 4 supplies the conditional selected-block transition evidence.

Add one-fact hostiles for an extra selector caller, arbitrary existing-page
argument, adjusted provider result, foreign/partial/indexed head writer,
missing reciprocal page link, broken singleton self-link, unresolved indirect
mutation, raw/decoded call disagreement, empty per-site origins, collective
origins missing provider or ring, different request normalization at one site,
missing or partial removal, removal through the wrong head/link field,
singleton removal that leaves a nonnull head, nonempty removal that breaks a
reciprocal link, an unresolved remover owner, a remover caller outside the
closed deallocator graph, a missing/duplicate call obligation, a semantic
remover invocation fabricated from an address inventory, missing head rotation,
rotation before success, and rotation of a different page. Retain wrong,
missing, partial, adjusted, and foreign remover arguments as Task 5 discharge
hostiles; Task 3 must never label them as `P` or `ring`.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_ring'
```

Expected: FAIL with `_publication_private_page_ring_role` missing.

- [ ] **Step 3: Implement structural ring discovery**

```python
def _publication_private_page_ring_role(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    layout: _PublicationPrivatePageLayout,
) -> _PublicationPrivatePageRingEvidence | None:
    """Prove a closed circular ring containing only provider pages."""
```

Start from `contract.large_allocator`, `contract.page_provider`, and
`contract.mutable_state`. Inventory every whole-image overlapping head
reader/writer, reconcile raw/recovered call edges, and prove every value written
to the head or page links is null, the exact provider return, or an existing
same-ring page. Use a finite `null/provider-page/ring-page` lattice with exact
per-site joins; never enumerate members. The first selector site in the exact
integration is intentionally a provider/ring join.

Discover the selector as the unique large-allocator callee whose complete
incoming inventory satisfies the per-site page subsets and identical request
lineage. Require one coherent pair of distinct publisher link writes, then
return an immutable copy of `layout` with those derived offsets; no earlier
task may populate them. Exact integration asserts `(0, 4)` only after
discovery. Type every `P`-relative page-link operand and emit spans keyed by
`(function_entry, instruction_address, operand_index)`.

Keep concrete head-slot accesses on the exact finite/global path, but retain
their reads, writes, global-slot dependency, and absolute-reference dependency.
Serialize insertion and rotation with their proved contextual invocations.
Serialize `ring-remove` as a conditional remover-body transfer with no
invocations, plus the separate closed call-obligation inventory. A successful
existing-ring selector call must dominate one rotation that writes the selected
page to the head. Instruction and call-address inventories are not semantic
authorization. Task 4, not Task 3, emits the
single durable `select` transfer; Task 3 retains the invocations that Task 4
must consume. Return layout, role, transfers, and spans only as one immutable
ring-evidence object so later mutation/replay phases cannot silently drop the
certified `ring-remove` transfer or its operand spans.

- [ ] **Step 4: Run ring/allocator tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_ring or private_heap_allocator or private_heap_effect'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): prove private page ring"
```

Expected: all selected tests pass before the commit.

---

### Task 4: Type the Selector's Page and Block Metadata Walk

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:19350-20550`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11300-12000`

**Interfaces:**
- Consumes: Task 3 `_PublicationPrivatePageRingEvidence`; it retains the ring
  transfers/spans unchanged while Task 4 adds selector evidence.
- Produces: an updated layout, a selector-seeded
  `_PublicationPrivateBlockArenaRole`, exactly one contextual `select`
  transfer, exact triple-keyed arena spans, and the process-local relational
  abstract domain used again by Task 5.

- [ ] **Step 1: Write RED selector tests**

```python
def test_private_block_selector_walks_only_same_page_blocks():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects, ring_evidence = (
        private_page_arena_ring(fixture)
    )
    layout = ring_evidence.layout
    ring = ring_evidence.role

    result = recovery._publication_private_block_selector_role(
        contract, extent, effects, ring_evidence
    )
    assert result is not None
    layout, role, select_transfer, spans = result

    assert layout.minimum_split_remainder is not None
    assert role.selector_entry == fixture.selector
    assert set(role.selector_calls) == set(fixture.selector_calls)
    assert select_transfer.role == "select"
    assert select_transfer.invocations == ring.selector_invocations
    assert all(
        invocation.block_state.allocation == "none"
        and invocation.block_state.membership == "none"
        for invocation in select_transfer.invocations
    )
    assert any(
        transition.before.allocation == "free"
        and transition.before.membership == "listed"
        and transition.after.allocation == "allocated"
        and transition.after.membership == "unlisted"
        for transition in select_transfer.state_transitions
    )
    assert all(len(key) == 3 for key in select_transfer.span_keys)
    assert {span.field for span in spans} >= {
        "extent", "largest-free", "sentinel", "block-header", "block-next",
        "successor-header",
    }
```

Run the positive once for a provider-only invocation, once for an existing-ring
invocation, and once with both origins joined at one call site. Require every
site to use the same normalized request lineage and require the selector to
emit one transfer shared by all contexts, not one transfer per call site. Add a
positive unknown two-successor branch whose successors both retain identical
recurrence and guard relations, proving that a benign join remains admissible.

Add one-fact hostiles for an extent clobber, changed size mask, foreign block
link, header sourced from mapped global memory, removed unsigned fit guard,
removed minimum-remainder guard, wrong failure largest-free update, unknown
loop branch, unsupported join, state-cap exhaustion, sentinel/page-end
off-by-one, successor-header/sentinel confusion, wrap in `B+S` or `B+R`, a
transfer with only some selector invocations, an extra select transfer, and an
extra unclassified memory operand or operand index. Also mutate the selector
input to split away from `free/listed`, make either ordered initializer call
conditional, alter either call's copied bit-2 argument, omit `B2` relinking,
make split return `allocated/listed`, omit unlink, omit unlink's bit-2 set or
exact `D`/singleton/reciprocal/`P+8` updates, or demand restoration before the
compound select return. Reject a selector invocation with a non-`none/none`
block state, or a state transition lacking its matching invocation context.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_block_selector'
```

Expected: FAIL with `_publication_private_block_selector_role` missing.

- [ ] **Step 3: Add the finite abstract value and selector worklist**

```python
@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaAbstractValue:
    kind: Literal[
        "zero", "page", "tagged-extent", "extent", "page-end", "sentinel",
        "block", "tagged-block-header", "block-size", "request-size",
        "remainder", "boundary-tag-size", "successor-header", "condition",
    ]
    extent_token_sha256: str
    same_page: bool
    allocation_state: Literal["none", "free", "allocated"]
    list_membership: Literal["none", "unlisted", "listed"]
    expression_token: int


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaPredicate:
    kind: Literal[
        "unsigned-fit", "minimum-remainder", "equal", "not-equal",
        "nullable", "adjacent", "flag-test",
    ]
    left_token: int
    right_token: int
    truth: bool


def _publication_private_block_selector_role(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
    ring_evidence: _PublicationPrivatePageRingEvidence,
) -> tuple[
    _PublicationPrivatePageLayout,
    _PublicationPrivateBlockArenaRole,
    _PublicationPrivateArenaTransfer,
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Type-check the large selector under the page/block invariant."""
```

Use a bounded CFG worklist and intern bounded expression tokens. Values and
predicates are distinct domains. Joins retain only identical relational facts;
`zero` joins only explicitly nullable fields. Explore both successors of an
unknown branch only when both successors type-check under the same retained
relations. An unknown loop/backedge, or either branch that loses the required
recurrence or guard relation, rejects. The only widening is the proved
same-page block recurrence at the certified circular-list backedge, so the
proof never enumerates block or page members; worklist states and interned
tokens have explicit finite caps and exhaustion rejects.

Track allocation and free-list membership as independent components. Stable
compound boundaries admit `free/listed` and `allocated/unlisted`. A nested
block-initializer return may carry `free/unlisted` for initializer base or
selector `B2` before split links it. `allocated/listed` is allowed only between
unlink's bit-2 set and detachment instructions, never at a call return. Resize
split returns `allocated/unlisted`. Mixed `none` states reject. Do not infer
links from the allocation bit, allocation from link loads, or demand the full
invariant at an instruction-local transient. Attach each transient to its exact
initializer/select/insert restoration obligation and reject escape or widening.

Bind the normalized request formal, tagged/masked extent, page end, exact
sentinel, tagged/masked block size, free-list recurrence, unsigned fit and
remainder guards, success/failure largest-free values, exact return, and every
real memory operand. Keep ordinary successor-header and terminal page-end-tag
alternatives separate internally. Serialize their shared exact `B+S` operand
as `region="successor", field="successor-header"` only after both alternatives
are proved; it must never include the `P+E-4` sentinel. Derive the unique
unsigned minimum split remainder and return an updated immutable layout.

Derive the input layout only from `ring_evidence.layout`; there is no separate
caller-supplied layout that could disagree with the retained ring proof.
Consume `ring_evidence.role.selector_invocations` exactly and emit one `select`
transfer whose invocation tuple contains all sites/contexts and whose span keys
are exact `(function_entry, instruction_address, operand_index)` triples. No
abstract state, worklist result, or inferred capability survives construction;
only the immutable layout, role seed, transfer, selector spans, and retained
ring evidence are durable. The
transfer records `free/listed` input and output around split, both sequential
block-initializer calls with copied input bit `2`, then unlink's
`free/listed -> allocated/unlisted` compound transition. Task 5 must bind exact
split, block-initialize, relinking, and unlink evidence before Task 6 may
publish it.

- [ ] **Step 4: Run selector tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_block_selector or private_page_ring or private_page_layout'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): type private block selector"
```

Expected: the positive selector and all hostiles pass before the commit.

---

### Task 5: Prove Every Arena Mutation Preserves the Invariant

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:19350-20850`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11300-12200`

**Interfaces:**
- Consumes: Task 4 abstract domain and selector role plus the unchanged Task 3
  `_PublicationPrivatePageRingEvidence`, including its insert/remove/rotate
  transfers, exact spans, and unresolved remover-call obligations.
- Produces: contextual `_PublicationPrivateArenaInvocation`,
  `_PublicationPrivateArenaStateTransition`, and
  `_PublicationPrivateArenaTransfer` rows; typed call edges; a complete
  `_PublicationPrivateBlockArenaRole`, and exact span inventories for the
  shared block initializer, split, unlink, insert, both coalescers, one
  first-class arena-free compound transfer, and bounded grow/shrink resize.
  Nested roles prove safe local postconditions; select, resize, arena-free/
  deallocator, and initializer-base compound boundaries prove full restoration.

- [ ] **Step 1: Write RED positive transfer tests**

```python
@pytest.mark.parametrize(
    "role",
    (
        "block-initialize",
        "split",
        "unlink",
        "insert",
        "coalesce-prev",
        "coalesce-next",
        "arena-free",
        "resize",
    ),
)
def test_private_arena_transfer_proves_contextual_postcondition(role):
    fixture = private_page_arena_image()
    recovery, inputs = private_page_arena_selector(fixture)

    result = recovery._publication_private_arena_transfer(
        role=role,
        **inputs,
    )
    assert result is not None
    transfer, spans = result
    assert transfer.role == role
    assert transfer.invocations
    assert transfer.span_keys
    assert all(len(key) == 3 for key in transfer.span_keys)
    assert transfer.function_sha256
    assert spans
```

Assert that `role.block_initializer_entries == (fixture.block_initializer,)`
and that the one `block-initialize` transfer binds its complete incoming
inventory: initializer base plus both sequential split sites under both
selector and resize contexts. This is three unique call addresses but five
contextual invocation rows. The split rows retain `B` versus `B2`, prove both
calls receive the allocation value copied from input `B` bit `2`, and serialize
these postconditions: initializer-base initial `B` is `free/unlisted`;
selector first-call `B` is `free/listed`; selector second-call `B2` is
`free/unlisted` until split links it; resize first-call `B` and second-call `B2`
are both `allocated/unlisted`. Both selector rows retain the `select`
restoration owner, and resize `B2` retains the `resize` owner even though its
abstract state pair is stable. Require the transfer's function dependency,
fingerprint, exact triple-keyed spans, and typed mutation edges.

```python
block_initialize_transfer = next(
    transfer for transfer in transfers if transfer.role == "block-initialize"
)
initializer_call, split_first_call, split_second_call = (
    fixture.block_initializer_calls
)
assert {
    (invocation.call_address, invocation.context)
    for invocation in block_initialize_transfer.invocations
} == {
    (initializer_call, "initializer-base"),
    (split_first_call, "selector-split"),
    (split_second_call, "selector-split"),
    (split_first_call, "resize-split"),
    (split_second_call, "resize-split"),
}
```

Add positive compound tests showing selector split starts and returns with
free/listed `B`, links free `B2`, and then unlink sets `B` bit `2` and detaches
it to `allocated/unlisted`, including exact `D`, singleton, reciprocal,
sentinel-head, and `P+8` handling. Resize split starts with
`allocated/unlisted` `B`, returns `allocated/unlisted` `B2`, and insert clears
bit `2` before listing the remainder on both grow and shrink paths. Require the
one insert transfer to bind its initializer-base,
arena-free, resize-grow, and resize-shrink invocation inventory with complete
spans, transitions, typed edges, fingerprints, and dependencies. The
initializer-base executions of insert and block initializer remain part of the
exact embedded effect closure, but later executions of both helpers must be
authorized only by their ordinary arena transfers.

Assert `role.arena_free_entries == (fixture.arena_free,)` and exactly one
`arena-free` transfer rooted in the closed deallocator context. Positive
retained-page and whole-page-release cases must serialize
`allocated/unlisted ->` insert-local `free/unlisted -> free/listed`, exact
payload and tagged-page recovery, nested insert/coalescer edges, and then either
the retained survivor at the deallocator restoration boundary or the exact
whole-page predicate followed by page-ring removal/release and `none/none`.
Prove private-free selects exactly one direct small/arena branch; retain the
small-free backing-page retirement call as a distinct arena-free invocation,
not a second direct interpretation of the original payload. Require the
arena-free function dependency,
fingerprint, complete triple-keyed spans, exact invocation/state-transition
rows, and every nested mutation/release edge. Every invocation has
`role="arena-free"`, `context="deallocator"`; every transient transition has
the exact enclosing deallocator restoration role and entry. Also prove
fixed-point admission of the bounded resize owner without adding it to the
deallocator closure.

Together the positive role tests must exercise stable `free/listed` and
`allocated/unlisted`, bounded `free/unlisted` at its exact nested locations,
and instruction-local `allocated/listed` only inside unlink. No invocation or
helper return may expose `allocated/listed`. Add malformed `none` pair tests so
`none/free`, `allocated/none`, and analogous partial states reject.

- [ ] **Step 2: Add the one-fact hostile matrix**

Add separate mutations for a missing/extra/reordered block-initializer call,
either split site made conditional or context-exclusive, an allocation argument
not copied from input `B` bit `2`, collapsed `B`/`B2` subjects, collapsed
allocation/membership state, missing initializer entry/dependency/span/transfer,
split without
`requested <= old_size`, split without the recovered minimum remainder,
overflowing/out-of-page split address, selector input not `free/listed`, omitted
selector `B2` relink, selector split return marked `allocated/listed`, resize
input/remainder not `allocated/unlisted`, a fabricated resize `free/unlisted`
remainder, transient escape at a compound return, unlink missing its bit-2 set,
successor flag, `D`, singleton, `P+8`, or reciprocal update, foreign
predecessor/successor,
arbitrary inserted block, missing head/sentinel transition, insert after
coalescing, insert listing before clearing bit `2`, previous coalesce without
the previous-free flag and boundary tag,
next coalesce without exact adjacency, removal of the wrong survivor,
successor/page-end confusion, relationally unproved coalesce sum or page
overrun, changed payload offset/page-pointer mask/flag, resize without complete
incoming calls, resize missing its grow coalesce/fit/remainder guard or returned
remainder insertion, unknown arena write, unclassified base/index metadata
write, partial-width metadata write, unresolved indirect edge, and a target
outside the exact dependency/call closure. Each hostile asserts rejection at
the narrowest transfer or role-assembly entry point.

Add insert-specific hostiles for a missing/retargeted initializer-base or later
invocation, missing later body span/dependency/transition/fingerprint, and an
effect authority installed simultaneously with arena authority at one exact
insert key. Reject a fabricated initializer-base call path that is absent from
the exact embedded effect closure. Add arena-free hostiles for a
missing/duplicate role or compound transfer, foreign payload, changed payload
offset/tag mask, a deallocator-context invocation with populated page origins
or a partial `none` block-state pair, missing
insert-local `allocated/unlisted -> free/unlisted -> free/listed` ordering,
private-free taking both or neither direct small/arena branch, a small payload
fed directly to arena-free, collapsed direct-arena and backing-page-retirement
invocations, reordered insert/coalescing, escaped transient, false whole-page
predicate, reordered page removal/release, a remover-shaped body detached from
the retained `ring-remove` transfer or carrying nonmatching ring span keys, a
missing/duplicate/foreign removal-call obligation, a retained obligation not
discharged as exact untagged `P`, a nested remover call absent from the retained
obligations, and every missing body/call/span/fingerprint/dependency fact.

- [ ] **Step 3: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_arena_transfer'
```

Expected: positives fail because the transfer checker is missing, while every
hostile retains a distinct pytest ID.

- [ ] **Step 4: Implement the transfer checker and role assembly**

```python
def _publication_private_arena_transfer(
    self,
    *,
    role: Literal[
        "block-initialize", "split", "unlink", "insert", "coalesce-prev",
        "coalesce-next", "arena-free", "resize",
    ],
    function_entry: int,
    invocations: tuple[_PublicationPrivateArenaInvocation, ...],
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
    layout: _PublicationPrivatePageLayout,
    ring_evidence: _PublicationPrivatePageRingEvidence,
) -> tuple[
    _PublicationPrivateArenaTransfer,
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Prove one role's local or compound contextual postcondition."""


def _publication_private_block_arena_role(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
    layout: _PublicationPrivatePageLayout,
    ring_evidence: _PublicationPrivatePageRingEvidence,
    selector_role: _PublicationPrivateBlockArenaRole,
    select_transfer: _PublicationPrivateArenaTransfer,
    selector_spans: tuple[_PublicationPrivateArenaSpan, ...],
) -> tuple[
    _PublicationPrivateBlockArenaRole,
    tuple[_PublicationPrivateArenaTransfer, ...],
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Discover and close every live metadata transfer role."""
```

Seed the already certified exact effect-closure initializer-base
block-initialize/insert calls separately, then seed formals for both ordered
block-initialize sites
in selector split, both ordered sites in resize split,
arena-free/deallocator, grow, and shrink contexts. Use
`_PublicationPrivateArenaBlockState` with independent `allocation` and
`membership` components on invocation inputs and transition `before`/`after`
states. Any transition to a transient must carry its non-null
`restoration_role` and exact `restoration_entry`. The initializer-base
invocation reconciles an incoming role call and shares the durable
`block-initialize` helper transfer, while its enclosing effects remain the
induction base; it does not create an `initialize` transfer. Start
all *new later* free/coalesce/arena-free discovery only at
`contract.deallocator_root`; the seeded initializer-base effects are not a
general alternate discovery root.
Require the Task 4 layout to equal `ring_evidence.layout` except for the exact
selector-derived fields Task 4 is authorized to populate; any disagreement in
the inherited page/header/link fields rejects.
Require its least reachable complete function/call closure, reconcile raw,
decoded, and provisional-residue edges with
`_least_reachable_incoming_call_domain_is_closed`, and store typed edges in the
block role. A null deallocator is allowed only when no certified returning path
or inventoried metadata writer needs free/coalesce semantics.

Discover the unique shared block initializer by successful structural checking
of its bounded header/page-flags/boundary writes, then require three exact call
addresses and five contextual invocation rows and store its entry in
`block_initializer_entries`. Every split execution must call first for `B` and
then for `B2`, passing the same allocation value copied from input `B` bit `2`.
Retain the exact subject and the five local postconditions described by the
positive test; reject mutually exclusive sites or a resize `free/unlisted`
result. Discover the unique arena
free owner by successful compound checking inside the deallocator closure,
store it in `arena_free_entries`, and bind its complete deallocator invocations
and nested call inventory in one `arena-free` transfer. Discover all other
callees only by successful structural transfer checking. Then close the complete
incoming domain of every discovered role. A new owner may enter
the mutation fixed point only when every relevant path type-checks as one
bounded resize context; record it in `mutation_context_entries`, emit typed
`resize-context` edges and grow/shrink invocation rows, and repeat closure. Do
not add a resize owner to `deallocator_function_entries` merely because it
calls a deallocator role. Require one coherent role assignment and reject an
unresolved indirect role edge, address-taken role without a complete finite
caller domain, or fixed-point overflow.

Interpret both successors of an inexact branch and refine only relations
proved by its comparison. Prove block-initialize's local geometry and state,
split's guards, both sequential initializer calls, copied bit-2 allocation
argument, and context-dependent list repair. Prove unlink's
`free/listed -> allocated/unlisted` transition, bit-2 set, successor
previous-allocation update, and exact `D`/singleton/reciprocal/sentinel/`P+8`
cases. Prove insert accepts either free or allocated unlisted input, clears bit
`2` before list use, reaches `free/listed`, and only then coalesces. Also prove
previous boundary-tag adjacency, next adjacency, survivor identity, resize
request normalization, grow/shrink guards, allocated/unlisted split remainder,
and insertion of every returned remainder.
Coalesce size arithmetic is accepted only from mathematical adjacency plus the
already-proved successor bound; retail does not need a carry instruction it
does not contain.

Prove arena-free as one ordered compound transfer: begin with an
`allocated/unlisted` payload, recover `B=Q-payload_offset` and `P` from the
tagged page word, invoke certified insert, bind its bit-2 clear to
`free/unlisted` before listing and coalescing, and then either restore stable
`free/listed` or prove the exact
single-usable-block page predicate before certified ring removal and release to
`none/none`. Every branch and nested edge must restore at the exact
deallocator root; deallocator closure entries and an insert transfer alone are
not equivalent evidence. The release branch must consume the exact retained
`ring-remove` transfer and its triple-keyed spans from `ring_evidence`, not
merely rediscover a remover-shaped function. It must also prove exact untagged
ring page `P` at argument zero for every retained
`remover_call_obligations` key and discharge those keys one-for-one. Task 5 may
use its now-complete payload overlay, page-pointer flag, typed-field writer
closure, and compound restoration proof; it may not trust a familiar
displacement or any opaque Task 3 caller expression.

Within private-free, prove the classifying predicate partitions the direct
small-free and arena-free edges: exactly one is taken for the original payload.
If small-free later retires its backing arena page, bind that separate nested
arena-free invocation and its distinct payload lineage; do not merge it with
the direct arena branch.

Bind block payload offset and page-pointer/allocated/previous-allocated flag
semantics from these complete contextual paths. At each nested helper return,
require its serialized local postcondition and unique compound restoration
owner; do not require the stable full invariant there. Require the full
invariant at every externally visible select, resize, deallocator, and
initializer-base boundary. Require an exact triple-keyed span for every
arena-derived memory operand, including every block-initializer, insert, and
arena-free operand.
Non-arena paths may perform unrelated read-only metadata work or hand off to an
already certified allocator/deallocator root, but may not write, consume, or
synthesize an arena capability. Reconcile every provisional raw site against
the final executable partition before success.

- [ ] **Step 5: Run transfer tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_arena_transfer or private_block_selector or private_page_ring'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): prove private arena transfers"
```

Expected: all selected tests pass before the commit.

---

### Task 6: Assemble Durable Evidence and Replay Every Dependency

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1660-1750`
- Modify: `tools/mwcc_retro/x86_cfg.py:19350-21050`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11500-12350`

**Interfaces:**
- Consumes: layout, immutable Task 3 ring evidence, block role, all ring/block
  transfers, and all spans from Tasks 2-5.
- Produces: `_PublicationPrivatePageArenaInvariant`, its builder, and its
  dependency replay validator. The invariant embeds the exact initializer
  effect closure as its induction base; `induction_substituted_entries` records
  the exact effect-executed/later-transfer intersection; there is no ordinary
  `initialize` transfer, exactly one `select` transfer, and exactly one
  `arena-free` compound transfer.

- [ ] **Step 1: Write the RED evidence-assembly test**

```python
def test_private_page_arena_invariant_serializes_complete_evidence():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects = private_page_arena_contract(fixture)

    invariant = recovery._publication_private_page_arena_invariant(
        contract, extent, effects
    )

    assert invariant is not None
    assert invariant.function_entries
    assert invariant.call_edges
    assert invariant.spans
    assert invariant.transfers
    assert invariant.initializer_effects == effects
    assert sum(row.role == "select" for row in invariant.transfers) == 1
    assert sum(row.role == "arena-free" for row in invariant.transfers) == 1
    assert {row.role for row in invariant.transfers} >= {
        "ring-insert", "ring-remove", "ring-rotate"
    }
    assert invariant.block_arena.arena_free_entries == (fixture.arena_free,)
    assert set(invariant.induction_substituted_entries) >= {
        fixture.block_initializer,
        fixture.block_inserter,
    }
    block_initializers = tuple(
        row for row in invariant.transfers if row.role == "block-initialize"
    )
    assert len(block_initializers) == 1
    assert block_initializers[0].function_entry \
        in invariant.block_arena.block_initializer_entries
    assert {
        (
            transition.context,
            transition.subject,
            transition.after.allocation,
            transition.after.membership,
            transition.restoration_role,
        )
        for transition in block_initializers[0].state_transitions
    } == {
        ("initializer-base", "initial-block", "free", "unlisted",
         "initializer-base"),
        ("selector-split", "split-block", "free", "listed", "select"),
        ("selector-split", "remainder-block", "free", "unlisted", "select"),
        ("resize-split", "split-block", "allocated", "unlisted", "none"),
        ("resize-split", "remainder-block", "allocated", "unlisted", "resize"),
    }
    assert all(
        (transition.restoration_entry is not None)
        == (transition.restoration_role != "none")
        for transition in block_initializers[0].state_transitions
    )
    assert all(row.role != "initialize" for row in invariant.transfers)
    assert {row.kind for row in invariant.dependencies} >= {
        "function", "global-slot", "absolute-reference",
    }
    assert all(
        len(key) == 3
        for row in invariant.transfers
        for key in row.span_keys
    )
    assert invariant.allocator_dependency_fingerprints \
        == extent.allocator_dependency_fingerprints
```

Independently derive the expected effect-executed/non-initializer-transfer
intersection from the fixture effects and completed transfers, and assert exact
tuple equality with `invariant.induction_substituted_entries`. The explicit
subset assertion above is the regression for the two known helpers, not an
allowlist that excludes additional intersecting helpers.

Add replay tests using `dataclasses.replace` for stale function/global-slot/
absolute-reference dependencies, a stale allocator fingerprint, stale or
replaced initializer effects, a removed/retargeted/context-changed typed call
edge, changed head slot, removed/duplicate/conflicting triple span key, changed
invocation or invocation order, collapsed/changed block state transition,
missing/retargeted restoration role or owner,
removed/duplicated block-initialize entry/transfer/call site, removed or extra
ordered split invocation, swapped split call order, changed `B`/`B2` subject,
changed copied bit-2 lineage, selector split marked `allocated/listed`, resize
remainder marked `free/unlisted`, unlink or insert correction omitted,
private-free small/arena exclusivity removed, direct and backing-page arena-free
invocations collapsed,
`induction_substituted_entries`, an entry outside the exact effect/transfer
intersection, a missing/duplicated/changed arena-free entry/transfer/invocation/
transition/restoration, changed role, an added ordinary `initialize` transfer,
zero/two select or arena-free transfers, changed layout/flag semantics, stale
extent token, a removed/reordered/duplicated ring transfer or ring span key,
removed/duplicated/changed remover-call obligations, a semantic invocation
fabricated at Task 3, a Task 5 discharge missing or not exact `P`,
and a fresh recomputation that differs in any field. Each altered
certificate must fail
`_publication_private_page_arena_invariant_is_current` without noting partial
dependencies.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_arena_invariant'
```

Expected: FAIL with the invariant builder/validator missing.

- [ ] **Step 3: Implement assembly and replay**

```python
def _publication_private_page_arena_invariant(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
) -> _PublicationPrivatePageArenaInvariant | None:
    """Assemble one durable exact page-ring/block-arena certificate."""


def _publication_private_page_arena_invariant_is_current(
    self,
    invariant: _PublicationPrivatePageArenaInvariant,
) -> bool:
    """Replay all function, edge, slot, layout, transfer, and span evidence."""
```

Canonicalize contextual invocations, state transitions, typed edges, spans,
transfer triple keys, function entries, `induction_substituted_entries`, role
entries, and dependencies; reject duplicates or conflicting exact keys before
publication. Derive the substitution entries as the exact intersection of
initializer-effect executed helper entries and helpers active in later arena
transfers, meaning transfers having at least one non-`initializer-base`
invocation; do not use a helper-name allowlist. Snapshot every function, concrete
global slot, and absolute reference in `_PublicationPrivateArenaDependency`
rows. Copy the complete allocator dependency fingerprint tuple and embed the
exact current initializer effect closure. Fingerprint every ring, selector,
mutation, block-initializer, insert, arena-free, deallocator, incoming-context,
and resize owner. Require the block-initialize transfer's helper entry, three
unique call addresses, five contextual invocations, ordered split-call pairs,
copied input bit-2 lineage, `B`/`B2` subjects, independent canonical
state-transition rows, exact call edges, spans, and function dependency even
though its initializer-base invocation also appears inside the embedded
induction-base effects.

Require the arena-free transfer's exact owner entry, deallocator invocation,
payload recovery, ordered state transitions, nested insert/coalescer and
optional ring-removal/release edges, full span inventory, fingerprint, and
dependencies.

Carry immutable ring evidence from Task 3 through selector and mutation
assembly. Require every retained ring transfer and span to appear unchanged in
the final aggregate, every transfer span key to resolve to exactly one aggregate
span, and every aggregate span to be referenced by its certified transfer. A
shared key is allowed only when its access, region, and field interpretation is
identical. The whole-page arena-free branch must reference the retained
`ring-remove` transfer rather than a fresh remover lookalike.
Retain the canonical Task 3 remover-call obligations unchanged, require the
arena-free compound transfer to discharge every obligation key exactly once as
exact `P`, and reject any extra nested remover call or surviving obligation.

Replay in fail-closed order: validate immutable shape/order/literals first;
replay allocator fingerprints and embedded initializer effects; replay
canonical dependencies plus raw/decoded/provisional-residue and contextual
incoming call closure; freshly recompute layout, ring, its removal-call
obligations, selector,
every induction-substituted helper, block-initializer/insert invocations and
local postconditions, both split calls and their bit-2/list effects, unlink's
selector correction, resize insert's clear-before-list correction,
private-free's mutually exclusive small/arena branch partition, arena-free and
resize compound restoration obligations, mutation contexts, edges, transfers,
and spans with no arena memo lookup; then require exact dataclass equality. Only
after equality may
dependencies be propagated or noted. Reject final assembly unless ring offsets
are distinct, the split minimum is positive, all flag meanings are distinct
and proved, there is one
select transfer, there is exactly one complete block-initialize transfer,
there is exactly one complete arena-free transfer, there is no initialize
transfer, every nested transient has exactly one compound
restoration owner, every compound return is stable, and every transfer key
names one exact span. Do not add a standalone or persistent arena cache.

- [ ] **Step 4: Run replay tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_arena_invariant or private_arena_transfer'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): bind private arena evidence"
```

Expected: all selected tests pass before the commit.

---

### Task 7: Consume Arena Spans in Publication Body Domains

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1580-1650`
- Modify: `tools/mwcc_retro/x86_cfg.py:50100-51200`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py:11400-12450`

**Interfaces:**
- Consumes: `_PublicationPrivatePageArenaInvariant`.
- Produces: exact span-and-invariant-backed
  `_PublicationBodyAddressDomainWitness` rows and a successful synthetic
  returning-closure audit with complete arena-context consumption.

- [ ] **Step 1: Write the RED integration test**

```python
def test_publication_body_uses_private_page_arena_invariant():
    fixture = private_page_arena_image()
    recovery, closure, bridge = private_page_arena_publication_inputs(fixture)

    witnesses = recovery._publication_body_address_domains(
        fixture.arena.callback_slot, closure, (bridge,)
    )

    assert witnesses is not None
    arena_witnesses = tuple(
        witness
        for witness in witnesses
        if witness.private_page_arena_invariant is not None
    )
    assert arena_witnesses
    assert all(witness.private_page_arena_span for witness in arena_witnesses)
    assert fixture.selector in {
        witness.returning_body.function_entry
        for witness in arena_witnesses
    }
    assert fixture.block_initializer in {
        witness.returning_body.function_entry
        for witness in arena_witnesses
    }
    assert fixture.block_inserter in {
        witness.returning_body.function_entry
        for witness in arena_witnesses
    }
    assert fixture.arena_free in {
        witness.returning_body.function_entry
        for witness in arena_witnesses
    }
```

Add integration hostiles for a missing body named by an active transfer edge,
especially an active induction-substituted helper or arena-free, a missing
block-initialize/insert/arena-free operand span or function dependency, a
collapsed/changed transient transition, either split initializer body context
missing, the two split sites treated as alternatives, changed copied bit-2
lineage, selector unlink or resize insert correction missing, private-free
small/arena contexts simultaneously active for one payload,
an extra body memory operand, conflicting arena contexts, a simultaneously
installed effect/arena exact-key overlap, disjoint arena/effect contexts
whose arena invariant embeds different effects, live alternate incoming edge,
arena memory hidden by effect-style execution pruning or transfer-instruction
skipping, excluded transfer/invocation owner, unused certified span, used
operand without a span, and a witness carrying only a span or only an
invariant. Include positives showing that a provider/initializer not present as
a returning body is still discovered from the contract and that an omitted
non-transfer dependency body or any other missing body with no active transfer
edge does not reject. Separate block-initializer and insert positives must
replay their initializer-base effects as induction evidence without installing
them as competing body-address contexts, then authorize later executions only
through complete arena spans. Separate hostiles that install both authorities
at one exact key for either helper must reject. Arena-free positives must cover
both retained-page and page-release outcomes; hostile omissions or reordering
of its compound transition/edges must reject. Include a positive private-free
partition test covering the direct small and direct arena arms separately plus
small-free backing-page retirement, and reject any merged payload lineage.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'publication_body_uses_private_page_arena or private_page_arena_integration'
```

Expected: FAIL because the body witness field/context is missing.

- [ ] **Step 3: Extend the body witness and context construction**

Add both optional fields to `_PublicationBodyAddressDomainWitness`:

```python
private_page_arena_span: _PublicationPrivateArenaSpan | None = None
private_page_arena_invariant: (
    _PublicationPrivatePageArenaInvariant | None
) = None
```

Discover candidate arena bases from allocator bridges/contracts independently
of the returning-body list; initializer and provider functions may be ordinary
dependency callees. Build arena invariants after initializer-effect contexts,
at most once per distinct proof input during this one body-domain call. Use a
local memo key containing allocator root, sorted explicit protected slots,
contract fingerprint, extent token, and exact initializer effects. The memo is
only construction deduplication: every supplied durable invariant still uses
Task 6 replay, and no memo persists across calls.

Build an O(1) function-to-context map. Reconcile the returning closure's active
edges with all contextual invocation rows, including every
`induction_substituted_entries` helper, arena-free/deallocator, and resize
context. Block-initialize gets one body context whose durable invocation tuple
covers initializer-base plus both sequential call sites under selector-split
and resize-split, retaining all five invocation rows, copied bit-2 lineage, and
`B`/`B2` subjects; insert gets one covering initializer-base plus arena-free
and resize calls with clear-before-list transitions. Each tuple covers its
independent before/after states. Neither helper's
exact operands are authorized merely because the original initializer effect
closure executed it. Arena-free gets its complete compound transfer context,
including the optional page-removal/release branch and both direct-arena and
small-free backing-page-retirement invocations. Private-free's direct small and
arena contexts remain mutually exclusive for the original payload.
Missing bodies reject only when an active transfer edge names them; any arena
transfer/invocation owner present in `excluded_functions` rejects.
For every function with an arena context, scan the complete body's memory
operands without effect-style executed-instruction pruning and without skipping
transfer instructions.

Associate exact triple-keyed spans with certified functions and reject any
conflicting contextual span. For every derived induction-substitution entry,
replay the initializer execution only inside induction validation and do not
install its effect span as later body authority; install only its complete
arena context. A true simultaneously installed exact effect-span/arena-span
key overlap rejects. Disjoint effect and arena contexts may coexist only when
the arena invariant embeds the same exact initializer effects. Let only the
pair of exact span plus its complete invariant supply the operand's private-heap
input/output domain. Derive and validate substitution generically from the exact
effect-executed/later-transfer intersection; do not special-case insert or
block initializer. Do not resolve an actual installed exact-key collision by
precedence.
Keep generic private-heap rejection unchanged. At each body exit,
require exact per-body arena span use:

```python
used_arena_span_keys == certified_arena_span_keys
```

Retain the final body fingerprint replay.

- [ ] **Step 4: Run focused publication/private-heap tests and commit**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'publication_body or private_heap or private_page or private_arena'
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): certify private arena bodies"
```

Expected: the positive integration and all preexisting/hostile selected tests
pass before the commit.

---

### Task 8: Run Local, Exact Mini-Query, and Full-Root Gates

**Files:**
- Modify: `build/diagnostics/task4-repair-exact/hydrate-cfg-query.py` (ignored)
- Modify: `docs/superpowers/plans/2026-08-06-private-page-arena-invariant.md`
- Modify: `.superpowers/sdd/2026-07-12-retail-pcode-proof/progress.md` (ignored
  operational ledger, if retained by the parent task)

**Interfaces:**
- Consumes: the complete local certificate.
- Produces: recorded local evidence, exact retail mini-query evidence, and one
  authoritative full-root result or next fail-closed boundary.

- [ ] **Step 1: Run complete local verification**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q
python -m py_compile \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
ruff check \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
```

Expected: every command exits zero. Record exact pass counts in this plan.

- [ ] **Step 2: Extend only the existing mini-query output**

Within the current `--private-heap-extent` branch, print the arena invariant,
selector calls and per-site origin contexts, page-head slot, typed role/call
edge counts, induction-substituted entries, block-initializer and insert
entries/invocations/state transitions, ordered split call pairs and copied bit-2
lineage, unlink/insert state corrections, private-free branch partition,
arena-free/deallocator and resize entries, canonical dependency-kind counts,
transfer roles, span count, and body-domain count. Do not add a parser option or
new artifact.

- [ ] **Step 3: Run the exact retail mini-query**

```bash
PYTHONPATH=. python \
  build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
  --scan-owned-blocks \
  --private-heap-extent 0x404610 0x403dd0 0x57fd78 \
  --no-semantic-trace
```

Expected: non-null contract, extent, initializer effects, arena invariant, and
body domains; provider `0x4042a0`; large allocator `0x4042f0`; page head
`0x57d2a0`; selector `0x403e30`; selector calls `0x404339`/`0x404372`; complete
provider/ring origin coverage; exactly one select transfer; no initialize
transfer; the exact derived induction-substitution set includes at least insert
`0x403ed0` and block initializer `0x403fd0`, with every additional intersecting
helper retained; one block-initialize transfer with the three exact
call addresses and five contextual invocations: initializer initial `B`
`free/unlisted`; selector first `B` `free/listed`, then `B2` `free/unlisted`
before relinking; resize `B` and `B2` both `allocated/unlisted`. Both split
sites execute sequentially and receive input `B` bit `2`. Selector unlink
produces `allocated/unlisted` with exact `D`/singleton/reciprocal/`P+8`
handling; resize insert clears bit `2` before listing, with no resize
`free/unlisted` return. Private-free selects exactly one direct small/arena
branch while retaining the distinct small-free backing-page retirement call;
one arena-free compound transfer for entry `0x404390`, rooted
in the complete classified deallocator closure with both retained-page and
exact whole-page-release obligations;
resize `0x4046d0`; function/global-slot/absolute-reference dependencies;
complete contextual roles and triple-keyed spans; wall time below two minutes.

If it fails, stop at the first structural mismatch and add a focused synthetic
RED test before changing production logic.

- [ ] **Step 4: Commit tracked validation notes and push before the long run**

```bash
git add \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  docs/superpowers/plans/2026-08-06-private-page-arena-invariant.md
git commit -m "test(mwcc-retro): validate private arena proof"
git push origin HEAD
```

Do not stage the ignored hydrated helper or operational ledger.

- [ ] **Step 5: Run the exact root only after all earlier gates pass**

```bash
/usr/bin/time -l env PYTHONPATH=. python \
  build/diagnostics/task4-repair-exact/hydrate-cfg-query.py \
  --scan-owned-blocks \
  --task4-publication-certificate \
  --task4-publication-root 0x435620 \
  --no-semantic-trace
```

Expected: `_publication_body_address_domains` passes `0x403e30`. Treat the
first later fail-closed stage, if any, as the next bounded Task 4 boundary; do
not broaden this certificate to suppress an unrelated failure.

- [ ] **Step 6: Hand back to the parent Task 4 gates**

After the first root passes, the parent plan owns the second publication root,
clean Task 7 replay, final full-suite validation, promotion, merge, issue
resolution, and queue refresh.
