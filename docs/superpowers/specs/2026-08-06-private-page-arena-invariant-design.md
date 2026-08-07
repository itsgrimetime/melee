# Private-Page Arena Invariant Design

**Date:** 2026-08-06
**Issue:** Melee tooling #1240
**Parent:** `2026-08-06-private-heap-bounded-interior-design.md`

## Decision

Add a role-derived, inductive private-page arena certificate to the returning-
publication address audit. The certificate proves that one allocator's page
ring contains only pages produced by its certified provider and that every
metadata operation preserves page and block bounds. It authorizes only the
exact memory operands recorded by that certificate.

The existing `_PrivateHeapAllocatorContract` remains the prerequisite for
allocator identity, call-graph closure, factory identity, mutable image-state
inventory, and protected-slot-disjoint concrete writes. The existing
`_PublicationPrivateHeapEffectClosure` remains the base-state proof for the
initializer call context. Neither is widened: a plain
`_PublicationPrivateHeapAddressDomain` still cannot authorize a dereference.

## Why a Separate Certificate Is Required

The allocator contract proves structural ownership, not memory safety. It does
not establish that a value loaded from a page-head slot is a provider result,
that page `+0xc` still contains the provider's extent token, or that block
sizes and links remain inside that page. The initializer effect proof establishes
those facts only for one freshly initialized page. It intentionally prunes
branches that are unreachable while the initial free-list sentinel is zero;
those branches become live after normal allocation and deallocation.

Two alternatives are rejected:

1. **Treat private-heap identity as dereference authority.** This loses the
   allocation extent and permits corrupted metadata to synthesize the protected
   image address.
2. **Extend exact initializer execution to arbitrary allocator state.** Page
   rings, free lists, splitting, and coalescing have unbounded concrete states.
   Exact execution would either bottom immediately or become an unbounded state
   search.

The selected certificate instead proves a finite structural invariant and a
finite set of invariant-preserving transfer roles.

## Retail Evidence, Not Production Rules

The first uncovered body is `0x403e30`. Its two complete raw/recovered incoming
calls are `0x404339` and `0x404372`, both owned by large allocator `0x4042f0`.
The first call supplies a page-ring member; the second supplies the result of
page provider `0x4042a0`. The provider calls factory `0x406480`, invokes
initializer `0x403dd0`, publishes the page through `0x404220`, and returns the
same page. Allocator root `0x404610` reaches the large allocator directly and
through its small-size replenishment path.

These addresses are exact integration assertions only. Production discovery
must not compare a function, call site, image slot, or owner against a retail
address or owner allowlist.

## Evidence Model

The implementation adds the following immutable evidence types. Literal fields
are structural classifications, not free-form claims.

```python
@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageLayout:
    extent_alignment: int
    block_alignment: int
    page_link_offsets: tuple[int, int] | None
    page_largest_free_offset: int
    page_extent_offset: int
    first_block_offset: int
    end_sentinel_displacement: int
    block_header_offset: int
    block_page_flags_offset: int
    block_prev_offset: int
    block_next_offset: int
    flag_mask: int
    minimum_split_remainder: int | None


@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageRingRole:
    head_slot: int
    provider_entry: int
    inserter_entry: int
    remover_entry: int | None
    provider_calls: tuple[int, ...]
    selector_page_calls: tuple[int, ...]
    head_reads: tuple[int, ...]
    head_writes: tuple[int, ...]
    ring_link_reads: tuple[int, ...]
    ring_link_writes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _PublicationPrivateBlockArenaRole:
    selector_entry: int
    selector_calls: tuple[int, ...]
    splitter_entries: tuple[int, ...]
    unlink_entries: tuple[int, ...]
    insert_entries: tuple[int, ...]
    coalescer_entries: tuple[int, ...]
    mutation_call_edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaSpan:
    function_entry: int
    instruction_address: int
    operand_index: int
    access: Literal["read", "write", "read-write"]
    region: Literal["page", "page-end", "block", "block-end"]
    field: Literal[
        "page-link",
        "largest-free",
        "extent",
        "sentinel",
        "block-header",
        "block-prev",
        "block-next",
        "boundary-tag",
    ]
    displacement: int
    width: int


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaTransfer:
    function_entry: int
    role: Literal[
        "initialize",
        "ring-insert",
        "ring-remove",
        "ring-rotate",
        "select",
        "split",
        "unlink",
        "insert",
        "coalesce-prev",
        "coalesce-next",
    ]
    instruction_addresses: tuple[int, ...]
    span_keys: tuple[tuple[int, int], ...]
    function_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageArenaInvariant:
    allocator_root: int
    factory_entry: int
    page_provider: int
    large_allocator: int
    extent_token_sha256: str
    layout: _PublicationPrivatePageLayout
    page_ring: _PublicationPrivatePageRingRole
    block_arena: _PublicationPrivateBlockArenaRole
    function_entries: tuple[int, ...]
    call_edges: tuple[tuple[int, int], ...]
    spans: tuple[_PublicationPrivateArenaSpan, ...]
    transfers: tuple[_PublicationPrivateArenaTransfer, ...]
    state_dependencies: tuple[tuple[Literal["global-slot"], int], ...]
    function_fingerprints: tuple[tuple[int, str], ...]
    allocator_dependency_fingerprints: tuple[tuple[int, str], ...]
```

The layout is recovered from the exact initializer and mutation shapes. Values
such as extent alignment, block alignment, field offsets, end displacement,
and split threshold are stored in the witness because the decoded program
proves them; they are not constants used to select a retail function. The
retail initializer establishes an extent alignment of `0x1000` and a block
alignment of `8`. This constrains `E` and block arithmetic, respectively; it
is explicitly **not** a claim that the provider return `P` is `0x1000`-aligned.
Initial layout recovery leaves `page_link_offsets` and
`minimum_split_remainder` null. Ring-role recovery must bind the unique
`P+0`/`P+4` link pair, and selector-role recovery must derive the unique
unsigned guard, before the final arena invariant is available.

The induction-base layout has the following exact field facts, recovered from
the certified initializer rather than used as selectors: `P+8` is the
largest-free size, `P+0xc` is `E | 3`, `P+0x10` is the first block,
`P+E-8` is its end boundary tag, and `P+E-4` is the end sentinel. A block
uses size at `+0`, page/flags at `+4`, and predecessor/successor links at
`+8`/`+0xc`. The page publisher, not the initializer effect closure, writes
the page-ring links at `P+0` and `P+4`.

## Structural Role Discovery

Discovery begins with a non-null `_PrivateHeapAllocatorContract` and its exact
bounded-interior extent/effect witness.

1. Use `contract.page_provider`, `contract.large_allocator`, and
   `contract.factory`; do not search the image for a familiar address. The
   Task 1 fixture must route this same provider/initializer/effect evidence
   into its page-ring graph; a separate illustrative graph is not evidence.
2. Recover the unique page-head candidate from non-executable mutable slots
   used by the large allocator as both a nullable page source and a page
   publication destination. Every overlapping whole-image writer must be
   reconciled before the role is available.
3. Recover the inserter as the unique provider-reachable function that accepts
   the exact provider result and either creates a self-linked page or splices it
   into the discovered circular ring. Recover a remover, when present, from the
   allocator/deallocator dependency closure by the inverse link and head-update
   shape.
4. Recover the selector as the unique large-allocator callee whose first
   argument is supplied on all incoming edges by either the provider result or
   a member obtained from the discovered ring, and whose other argument is the
   normalized request size. Raw bytes, decoded direct targets, source/target
   indexes, and the complete incoming-call inventory must agree.
5. Discover split, unlink, insert, and coalesce roles only from calls reachable
   from the selector or companion deallocator and only when their transfer
   shapes type-check against the recovered layout. Unknown or conflicting role
   assignments reject the whole certificate.

Exactly one coherent role graph is required. Missing roles may be absent only
when no certified path needs their transfer; duplicate candidates, unresolved
indirect edges, extra incoming callers, or state writers bottom the proof.

## Inductive Invariant

For each provider allocation, the certificate introduces a symbolic region
`Page(P, E)` tied to the existing extent token. Arithmetic is mathematical
until an explicit no-wrap check proves a concrete x86 address interval.

The page invariant is:

- `E` satisfies the provider's minimum, `0x1000` extent-alignment, and
  no-wrap proof. The invariant makes no alignment claim about `P` itself.
- The page header, first block, and end sentinel are contained in `[P, P+E)`.
- Both page links are null only while unpublished; once published they name
  pages carrying the same allocator-root capability. A singleton names itself
  in both directions.
- Masking the page extent field by the recovered flag mask yields exactly `E`.
- The largest-free field is zero or no greater than the usable arena extent.

The block invariant for `Block(P, E, B, S)` is:

- Block arithmetic uses the recovered `8`-byte block alignment; this remains
  distinct from extent alignment and does not imply an alignment property of
  `P`.
- The complete block metadata span lies inside the page arena.
- Masking the block header by the recovered flag mask yields `S`.
- `B + S` does not wrap and does not pass the recovered end boundary.
- Free-list predecessor and successor values are block capabilities for the
  same page; the list sentinel is the separately typed page-end cell.
- A boundary tag is used only at the exact derived end of a certified block.

Loads from region memory do not become capabilities merely because their
offset resembles a field. They receive a page, block, size, or sentinel type
only when every inventoried writer of that exact field is a certified transfer.

## Preservation Proof Boundary

The initializer effect witness is the induction base. Its exact `P`/`E`
execution must establish the recovered layout and initial page/block invariant.

Each subsequent transfer is checked symbolically for all states satisfying the
invariant:

- ring insertion/removal/rotation may copy only existing page capabilities and
  must preserve both link directions and the head's null/singleton semantics;
- selection may follow only same-page block links and may return only a
  certified block or null;
- splitting requires `requested <= S`, a nonwrapping split address, and the
  decoded minimum-remainder guard before constructing a second block;
- unlink/insert may copy only same-page free-list capabilities and must update
  both sides of every modified link;
- coalescing requires an adjacent-block or boundary-tag proof, performs a
  checked size sum, and cannot extend past the original page boundary.

The certificate covers allocator metadata accesses only. It does not prove
client payload correctness, admit external mutation of allocator metadata, or
authorize a capability after it escapes to an unrelated body. A function is
covered only if all of its real memory operands are private stack, existing
finite/global domains, existing initializer-effect spans, or exact arena spans.
Any unclassified memory operand bottoms that function and therefore the
certificate.

## Publication-Audit Integration

`_publication_body_address_domains` builds arena contexts after existing
initializer effect contexts. It associates an arena context with every
certified transfer function that is present in the returning closure. For an
exact `(instruction_address, operand_index)` match, the new span authorizes a
private-page or private-block dereference and records the complete invariant in
`_PublicationBodyAddressDomainWitness` through a new optional
`private_page_arena_invariant` field.

No generic fallback is added. A plain `_PublicationPrivateHeapAddressDomain`,
a field-offset match without a span record, an instruction skipped by the
transfer proof, or a function with two conflicting arena contexts still
returns `None`. At the end of each body, the used span set must equal its exact
certified span inventory.

## Serialization and Dependency Replay

The certificate is durable evidence, not a process-local inference. Before it
is consumed or reused, replay must verify:

- the exact allocator dependency entry/fingerprint tuple already bound by the
  extent witness;
- every additional page-ring or block-transfer function fingerprint;
- every recovered/raw direct call edge and complete incoming-call inventory;
- every page-head read/write and the global-slot dependency snapshot;
- the extent token, initializer effect closure, recovered layout, transfer
  inventory, and exact span keys.

Dependency rows include each function and each discovered concrete global slot.
The producer dependency snapshot remains the cache invalidation mechanism. The
first implementation adds no independent long-lived arena cache; any later
cache must store the complete immutable certificate and use normal dependency
memo replay.

## Fail-Closed Hostile Matrix

The certificate must reject each independent mutation:

- an extra selector caller or either legitimate selector call passing a
  non-page value;
- an adjusted provider result, mismatched extent token, or missing initializer;
- an unresolved, indirect, or raw/decoded-disagreeing role edge;
- a foreign, partial-width, indexed-unbounded, or overlapping writer to the
  page-head slot;
- a page-ring link sourced from an arbitrary argument or mapped global;
- a missing reciprocal page-link update or broken singleton case;
- a post-initializer extent-field write, changed mask, or unbounded extent
  arithmetic;
- an unaligned or unbounded block-size write;
- a block predecessor/successor sourced outside the same page;
- a missing reciprocal free-list update;
- removal of the size-versus-request guard or minimum split-remainder guard;
- an end-sentinel or boundary-tag off-by-one, wrap, or out-of-page access;
- coalescing without a proved adjacent block or with an unchecked size sum;
- an unknown branch, extra memory operand, stale fingerprint, changed state
  dependency, or live alternate incoming edge hidden by pruning.

Each hostile changes one fact while retaining the surrounding valid shape so
that rejection is attributable to the intended rule.

## Validation Gates

1. Focused synthetic RED/GREEN tests for role discovery, induction base,
   individual preservation roles, dependency replay, and body-domain use.
2. The existing publication/private-heap selection, `py_compile`, Ruff, and
   `git diff --check`.
3. Extend the existing ignored hydrated diagnostic's
   `--private-heap-extent` output; do not add a new CLI or helper. The exact
   mini-query must identify the two selector calls, page-head slot, full role
   graph, and all certified spans while remaining under two minutes.
4. Run the full exact `0x435620` root only after the mini-query and local suite
   pass. A later full `0x435a8c` root and clean Task 7 replay remain parent-plan
   gates, not development probes.

## Non-Goals

- No retail-address checks, owner allowlists, symbol-name checks, or byte-string
  signatures that select a known compiler body.
- No generic `private-heap + offset` permission.
- No attempt to prove arbitrary allocator implementations or recover client
  object layouts.
- No weakening of protected-slot, image-capability, reference-disjointness, or
  raw-control-flow closure checks.
- No full root replay while developing an individual transfer rule.
