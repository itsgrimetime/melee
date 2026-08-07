# Private-Page Arena Invariant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Certify the exact page-ring and block-arena metadata accesses reached
through a closed private allocator without granting generic private-heap
dereference authority.

**Architecture:** Keep `_PrivateHeapAllocatorContract` as the structural
prerequisite and `_PublicationPrivateHeapEffectClosure` as the induction base.
Discover page-ring and block-transfer roles from those contracts, prove a
finite invariant over symbolic page/block capabilities, serialize the exact
roles and spans, and let `_publication_body_address_domains` consume only
operand-keyed arena evidence.

**Tech Stack:** Python 3, Capstone x86 decoding, pytest, Ruff, and the existing
hydrated raw-CFG diagnostic.

## Global Constraints

- Production discovery must not compare a function, call site, image slot, or
  owner against a retail address or owner allowlist.
- A plain `_PublicationPrivateHeapAddressDomain` must remain insufficient for
  every real memory dereference.
- Begin with a non-null `_PrivateHeapAllocatorContract` and the exact existing
  extent/effect witness; do not create a parallel allocator recognizer.
- Recover layout values and transfer roles from decoded evidence rather than
  symbol names, byte-string identity, or familiar constants used as selectors.
- Keep `extent_alignment == 0x1000` distinct from `block_alignment == 8`.
  These constrain `E` and block arithmetic; do not infer or assert that `P`
  is page-aligned.
- Every unresolved edge, extra caller/writer, unknown abstract value, conflicting
  role, unclassified memory operand, or stale dependency fails closed.
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
  non-vacuous boundary regression showing that the existing allocator,
  extent, and initializer-effect proofs reach the selector but the current
  body audit bottoms there.

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
    splitter: int
    unlinker: int
    block_inserter: int
    coalescers: tuple[int, int]


def private_page_arena_image(
    *, mutation: str | None = None
) -> PrivatePageArenaFixture:
    """Return one closed synthetic page ring and block arena."""
```

Extend the existing synthetic private allocator and its actual
`_PublicationPrivateHeapExtentWitness` / `_PublicationPrivateHeapEffectClosure`
producer; do not place a disconnected page-arena image beside it. Both
selector paths must enter the same selector: one receives a member loaded from
a circular page ring, and one receives the exact page-provider result. Its
certified initializer must write `P+8` largest-free size, `P+0xc` as `E | 3`,
the first block at `P+0x10`, the end boundary tag at `P+E-8`, and the sentinel
at `P+E-4`; the first block must expose size `+0`, page/flags `+4`, and links
`+8`/`+0xc`. The page publisher must write the ring links at `P+0`/`P+4`.
The selector iterates a circular free list, optionally splits and unlinks a
block, and returns it. The companion free path exercises insertion and both
coalescing directions.

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
    assert effects.spans  # The induction base is real, not a fake bridge.

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

> **Plan correction note (2026-08-07):** The first Task 1 fixture audit found
> that its page-ring graph was disconnected from the existing
> extent/effect producer, while Task 2 assumed unavailable effect spans for
> page links and a single overloaded alignment value. Task 1 remains unchecked
> until the fixture is one coherent allocator/effect graph and the boundary
> regression proves the real selector is reached with non-empty induction-base
> evidence. Task 2 now derives only initializer layout; Task 3 binds page links
> from publisher evidence.

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
    assert layout.end_sentinel_displacement == -4
    assert layout.block_header_offset == 0
    assert layout.block_page_flags_offset == 4
    assert layout.block_prev_offset == 8
    assert layout.block_next_offset == 12
```

Add parametrized mutations for a changed extent mask, changed sentinel
displacement, missing first-block construction, out-of-range initial boundary
tag, missing `P+8` largest-free initialization, changed block page/flag field,
and an initializer effect that omits one layout operand. Each hostile must
assert a `None` layout result. A page-link write is deliberately not a Task 2
input: it belongs to the Task 3 publisher proof.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'private_page_layout'
```

Expected: FAIL with `_publication_private_page_layout` missing.

- [ ] **Step 3: Add the spec dataclasses and layout recognizer**

Add `_PublicationPrivatePageLayout`, `_PublicationPrivatePageRingRole`,
`_PublicationPrivateBlockArenaRole`, `_PublicationPrivateArenaSpan`,
`_PublicationPrivateArenaTransfer`, and
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

Replay contract, extent, and effect fingerprints. Decode the exact certified
provider/initializer body together with its effect spans to derive `P+8`
largest-free, `P+0xc` extent/flag word (`E | 3`), first block `P+0x10`, end
tag `P+E-8`, sentinel `P+E-4`, and block size/page-flags/prev/next fields
`+0/+4/+8/+0xc`. Derive `extent_alignment == 0x1000` and
`block_alignment == 8` separately; neither establishes alignment of `P`.
Reject duplicate layouts, wrap, or any initializer span outside `[P, P+E)`.
Set `page_link_offsets=None`: exact `P+0`/`P+4` links are not part of the
initializer effect evidence and Task 3 alone may bind them. The split threshold
remains absent until Task 4 binds its unique selector guard, so represent it as
`int | None` and require a non-null value in the final certificate.

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
  link offsets and `_PublicationPrivatePageRingRole` from
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
    layout, ring = ring_result
    assert layout.page_link_offsets == (0, 4)
    assert ring.head_slot == fixture.page_head_slot
    assert ring.provider_entry == fixture.page_provider
    assert ring.inserter_entry == fixture.page_inserter
    assert set(ring.selector_page_calls) == set(fixture.selector_calls)
    assert ring.head_writes
    assert ring.ring_link_writes
```

The ring dataclass keeps `selector_page_calls` distinct from `provider_calls`;
the implementation must populate and replay both inventories.

Add one-fact hostiles for an extra selector caller, arbitrary existing-page
argument, adjusted provider result, foreign/partial/indexed head writer,
missing reciprocal page link, broken singleton self-link, unresolved indirect
mutation, and raw/decoded call disagreement.

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
) -> tuple[
    _PublicationPrivatePageLayout,
    _PublicationPrivatePageRingRole,
] | None:
    """Prove a closed circular ring containing only provider pages."""
```

Start from `contract.large_allocator`, `contract.page_provider`, and
`contract.mutable_state`. Inventory every whole-image overlapping head
reader/writer, reconcile raw/recovered call edges, and prove every value written
to the head or page links is null, the exact provider return, or an existing
same-ring page. Use the finite lattice `null/provider-page/ring-page/bottom`;
never enumerate members. Discover the selector as the unique large-allocator
callee whose complete incoming inventory receives a page from the provider arm
or ring arm. Require publisher writes of exactly `P+0` and `P+4`, then return
an immutable copy of `layout` with `page_link_offsets == (0, 4)`; no earlier
task may populate those offsets.

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
- Consumes: page layout and ring role.
- Produces: selector `_PublicationPrivateBlockArenaRole`, arena spans, and the
  finite invariant abstract domain.

- [ ] **Step 1: Write RED selector tests**

```python
def test_private_block_selector_walks_only_same_page_blocks():
    fixture = private_page_arena_image()
    recovery, contract, extent, effects, layout, ring = (
        private_page_arena_ring(fixture)
    )

    layout, role, spans = recovery._publication_private_block_selector_role(
        contract, extent, effects, layout, ring
    )

    assert layout.minimum_split_remainder is not None
    assert role is not None
    assert role.selector_entry == fixture.selector
    assert set(role.selector_calls) == set(fixture.selector_calls)
    assert {span.field for span in spans} >= {
        "extent", "sentinel", "block-header", "block-next"
    }
```

Add hostiles for an extent clobber, changed mask, foreign block link, header
sourced from mapped global memory, removed size/request guard, unknown loop
branch, sentinel off-by-one, and an extra unclassified memory operand.

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
        "zero", "page", "extent", "request-size", "block",
        "block-size", "sentinel", "condition",
    ]
    extent_token_sha256: str
    same_page: bool


def _publication_private_block_selector_role(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
    layout: _PublicationPrivatePageLayout,
    ring: _PublicationPrivatePageRingRole,
) -> tuple[
    _PublicationPrivatePageLayout,
    _PublicationPrivateBlockArenaRole,
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Type-check the large selector under the page/block invariant."""
```

Use a bounded CFG worklist. Joins accept identical kind/page tokens; `zero`
joins only explicitly nullable page/sentinel fields. Loops stabilize on the
`block` type instead of enumerating nodes. Bind the request formal, masked
extent, page end, block-size mask, circular recurrence, size guard, exact
return, and every real memory operand. Derive the unique unsigned split-
remainder threshold and return an updated immutable layout with that value.

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
- Consumes: Task 4 abstract domain and selector role.
- Produces: `_PublicationPrivateArenaTransfer` rows and complete span
  inventories for split, unlink, insert, and coalescing roles.

- [ ] **Step 1: Write RED positive transfer tests**

```python
@pytest.mark.parametrize(
    "role",
    (
        "split",
        "unlink",
        "insert",
        "coalesce-prev",
        "coalesce-next",
    ),
)
def test_private_arena_transfer_preserves_invariant(role):
    fixture = private_page_arena_image()
    recovery, inputs = private_page_arena_selector(fixture)

    transfer, spans = recovery._publication_private_arena_transfer(
        role=role,
        **inputs,
    )

    assert transfer.role == role
    assert transfer.span_keys
    assert transfer.function_sha256
    assert spans
```

- [ ] **Step 2: Add the one-fact hostile matrix**

Add separate mutations for split without `requested <= old_size`, split without
the recovered minimum remainder, overflowing/out-of-page split address,
foreign predecessor/successor, either missing reciprocal unlink update,
arbitrary inserted block, missing head/sentinel update, previous coalesce
without a boundary tag, next coalesce without adjacency, coalesce size wrap or
page overrun, unclassified base/index metadata write, partial-width metadata
write, and a target outside the allocator dependency closure. Each mutation
asserts `_publication_private_arena_transfer(...) is None`.

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
        "split", "unlink", "insert", "coalesce-prev", "coalesce-next"
    ],
    function_entry: int,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    layout: _PublicationPrivatePageLayout,
    ring: _PublicationPrivatePageRingRole,
) -> tuple[
    _PublicationPrivateArenaTransfer,
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Prove one mutation preserves the recovered arena invariant."""


def _publication_private_block_arena_role(
    self,
    contract: _PrivateHeapAllocatorContract,
    extent: _PublicationPrivateHeapExtentWitness,
    effects: _PublicationPrivateHeapEffectClosure,
    layout: _PublicationPrivatePageLayout,
    ring: _PublicationPrivatePageRingRole,
) -> tuple[
    _PublicationPrivateBlockArenaRole,
    tuple[_PublicationPrivateArenaTransfer, ...],
    tuple[_PublicationPrivateArenaSpan, ...],
] | None:
    """Discover and close every live metadata transfer role."""
```

Seed formals with types proved at the complete incoming-call inventory.
Interpret both successors of an inexact branch; refine only relations proved by
the comparison. Require the invariant at every return and an exact span for
every real memory operand. Discover callees by structural transfer success,
require one coherent role assignment, reconcile direct edges, and reject any
live metadata function not classified by a successful transfer.

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
- Consumes: layout, ring, block role, transfers, and spans from Tasks 2-5.
- Produces: `_PublicationPrivatePageArenaInvariant`, its builder, and its
  dependency replay validator.

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
    assert invariant.state_dependencies == (
        ("global-slot", fixture.page_head_slot),
    )
    assert tuple(entry for entry, _sha256 in invariant.function_fingerprints) \
        == invariant.function_entries
    assert invariant.allocator_dependency_fingerprints \
        == extent.allocator_dependency_fingerprints
```

Add replay tests using `dataclasses.replace` for a stale function fingerprint,
stale allocator fingerprint, removed call edge, changed head slot, removed or
duplicate span key, changed layout, and stale extent token. Each altered
certificate must fail `_publication_private_page_arena_invariant_is_current`.

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

Sort and deduplicate tuples; reject conflicting `(address, operand_index)` span
classifications; copy the complete allocator dependency fingerprint tuple;
fingerprint every additional transfer function; and note producer dependencies
for every function and concrete state slot. Replay raw/decoded direct edges,
complete incoming calls, state dependencies, layout, transfers, and exact span
keys. Reject final assembly unless `layout.page_link_offsets == (0, 4)` and
`layout.minimum_split_remainder` is positive. Do not add a standalone arena
cache.

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
- Produces: arena-backed `_PublicationBodyAddressDomainWitness` rows and a
  successful synthetic returning-closure audit.

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
    assert fixture.selector in {
        witness.returning_body.function_entry
        for witness in arena_witnesses
    }
```

Add integration hostiles for a missing certified body, extra body memory
operand, conflicting arena contexts, live alternate incoming edge hidden by
pruning, unused certified span, and used operand without a span.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q \
  -k 'publication_body_uses_private_page_arena or private_page_arena_integration'
```

Expected: FAIL because the body witness field/context is missing.

- [ ] **Step 3: Extend the body witness and context construction**

Add this optional field to `_PublicationBodyAddressDomainWitness`:

```python
private_page_arena_invariant: (
    _PublicationPrivatePageArenaInvariant | None
) = None
```

Build arena invariants after initializer effect contexts. Associate exact span
maps with certified functions, reject conflicts, replay the invariant before
use, and let only an exact span supply the operand's private-heap input/output
domain. Keep generic private-heap rejection unchanged. Require exact span use:

```python
used_arena_spans == set(body_arena_spans.values())
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
selector calls, page-head slot, roles, span count, and body-domain count. Do not
add a parser option or new artifact.

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
roles/spans; wall time below two minutes.

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
