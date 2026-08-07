# Private-Page Arena Invariant Design

**Date:** 2026-08-06
**Reviewed amendment:** 2026-08-07
**Issue:** Melee tooling #1240
**Parent:** `2026-08-06-private-heap-bounded-interior-design.md`

## Decision

Add a role-derived, inductive private-page arena certificate to the returning-
publication address audit. The certificate proves that one allocator's page
ring contains only pages produced by its certified provider and that every
arena metadata operation preserves page and block bounds. It authorizes only
the exact memory operand recorded by an exact arena span.

The existing `_PrivateHeapAllocatorContract` remains the prerequisite for
allocator identity, call-graph closure, factory identity, mutable image-state
inventory, and protected-slot-disjoint concrete writes. The existing
`_PublicationPrivateHeapEffectClosure` remains the induction base and is
embedded unchanged in the final arena invariant. Layout recovery consumes its
selected paths, call contexts, affine destinations, values, masks, and exact
symbolic writes; initializer execution is not represented as an ordinary arena
transfer.

This widens serialized evidence, not authority. A plain
`_PublicationPrivateHeapAddressDomain`, a familiar field displacement, or a
transfer instruction inventory cannot authorize a dereference. The final body
witness must carry both the exact operand span and the complete current arena
invariant.

## Why a Separate Certificate Is Required

The allocator contract proves structural ownership, not memory safety. It does
not establish that a value loaded from a page-head slot is a provider result,
that page `+0xc` still contains the provider's extent token, or that block
sizes and links remain inside that page. The initializer effect proof
establishes those facts only for one freshly initialized page. It intentionally
prunes branches that are unreachable while the initial free-list sentinel is
zero; those branches become live after allocation, deallocation, and resize.

Two alternatives remain rejected:

1. **Treat private-heap identity as dereference authority.** This loses the
   allocation extent and permits corrupted metadata to synthesize a protected
   image address.
2. **Extend exact initializer execution to arbitrary allocator state.** Page
   rings, free lists, splitting, coalescing, and resize have unbounded concrete
   states. Exact execution would bottom or become an unbounded state search.

The selected certificate proves a finite structural invariant and a finite set
of context-sensitive, invariant-preserving transfer roles.

## Retail Evidence, Not Production Rules

The first uncovered body is `0x403e30`. Its two complete raw/recovered incoming
calls are `0x404339` and `0x404372`, both owned by large allocator `0x4042f0`.
At the first site, the page argument is a join: it is either the exact result of
the initial provider call or a page loaded from and advanced through the ring.
At the second site it is the exact result of the exhaustion provider call. Each
site has a nonempty subset of the allowed origins and their union contains both
`provider` and `ring`. Both calls receive the identical normalized request
lineage formed by `(request + 0xf) & ~7` with a `0x50` floor in the large
allocator. Successful selection from an existing page rotates that page into
the page-head slot.

The provider `0x4042a0` calls factory `0x406480`, invokes initializer
`0x403dd0`, publishes through `0x404220`, and returns the same page. Allocator
root `0x404610` reaches the large allocator directly and through its small-size
replenishment path.

The exact mutation graph is context-sensitive:

- block initializer `0x403fd0` is called from initializer `0x403dfd`. Every
  split invocation then executes both sites `0x40408f` and `0x4040a6`
  sequentially; they are not context alternatives. Split snapshots input
  block-header bit `2` and passes that same allocation value for both `B` and
  `B2=B+R`;
- insert `0x403ed0` is called from initializer `0x403e22`, arena free
  `0x4043a7`, and resize sites `0x4047c4` and `0x40486b`;
- arena free is entry `0x404390`, called from small-free page retirement at
  `0x4045e4` and the direct arena branch of private-free at `0x4046b1`; its
  complete structurally classified deallocator invocation domain is part of
  the compound transfer rather than being inferred from the insert call alone;
- split `0x404020` is called from selector `0x403ea0` and resize sites
  `0x4047b3` and `0x40485a`;
- unlink `0x403f60` is called from selector `0x403ebc`;
- coalesce-prev `0x4040e0` is called from insert `0x403f2c`;
- coalesce-next `0x404180` is called from insert `0x403f39` and resize
  `0x404796`.

The exact initializer effect closure executes initializer `0x403dd0`, insert
helper `0x403ed0`, and block initializer `0x403fd0`. Both helpers are later
reused by ordinary arena transfers. Their initializer-base executions remain
induction evidence, but they cannot authorize later helper-body dereferences;
those later contexts require complete arena transfers and spans.

The two split-to-initializer sites are one ordered pair in every split context.
For selector input, `B` is `free/listed`: the first call preserves that state,
the second creates `B2` as `free/unlisted`, and split splices `B2` next to `B`
before returning with both blocks `free/listed`. Selector then calls unlink,
which sets header bit `2`, updates the successor previous-allocation bit, and
detaches `B`, yielding `allocated/unlisted`; its proof includes the exact `D`
head, singleton, reciprocal-link, and `P+8` largest-free cases. For resize
input, `B` is `allocated/unlisted`: both initializer calls preserve bit `2`,
both `B` and returned `B2` remain `allocated/unlisted`, and insert clears bit
`2` before it lists `B2`. There is no selector split return in
`allocated/listed`, no resize `free/unlisted` remainder, and no path on which
only one split initializer site executes. The initializer-base call alone
returns `free/unlisted` before its enclosing exact initializer inserts the
initial block.

The resize owner is `0x4046d0`. It is not in the outgoing closure of allocator
root `0x404610` or companion deallocator root `0x404650`; it is admitted only
by closing the complete incoming contexts of already discovered roles. The
deallocator root has raw `E8` byte occurrences in certified unreachable
executable residue, so raw closure must use the existing least-reachable caller
and final residue reconciliation rather than blind raw/decoded set equality.
Private-free `0x404650` classifies a non-null payload once and takes exactly one
direct branch: small-free `0x404590` at `0x4046a5` or arena-free `0x404390` at
`0x4046b1`. The small branch may later retire a backing arena page through its
own certified `0x4045e4` arena-free call, but the original payload cannot flow
through both direct branches or carry both small and arena capabilities.

Every address and constant in this section is an exact integration assertion.
Production discovery must not compare a function, call site, slot, owner,
incoming count, or constant against a retail address or allowlist.

## Evidence Model

The implementation adds immutable evidence types adjacent to the existing
publication evidence. Literal fields are closed structural classifications,
not free-form claims.

```python
@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageLayout:
    extent_alignment: int
    block_alignment: int
    page_link_offsets: tuple[int, int] | None
    page_largest_free_offset: int
    page_extent_offset: int
    first_block_offset: int
    page_end_tag_displacement: int
    end_sentinel_displacement: int
    block_header_offset: int
    block_page_flags_offset: int
    block_prev_offset: int
    block_next_offset: int
    block_boundary_tag_displacement: int
    size_flag_mask: int
    minimum_split_remainder: int | None


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaBlockState:
    allocation: Literal["none", "free", "allocated"]
    membership: Literal["none", "unlisted", "listed"]


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaInvocation:
    caller_entry: int
    call_address: int
    callee_entry: int
    role: Literal[
        "ring-insert", "ring-remove", "ring-rotate", "select",
        "block-initialize", "split", "unlink", "insert", "coalesce-prev",
        "coalesce-next", "arena-free", "resize",
    ]
    context: Literal[
        "provider", "initializer-base", "selector-ring",
        "selector-provider", "selector-split", "deallocator",
        "resize-split", "resize-grow", "resize-shrink",
    ]
    page_origins: tuple[Literal["provider", "ring"], ...]
    block_state: _PublicationPrivateArenaBlockState


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaStateTransition:
    function_entry: int
    role: Literal[
        "block-initialize", "split", "unlink", "insert", "coalesce-prev",
        "coalesce-next", "arena-free", "select", "resize",
    ]
    context: Literal[
        "initializer-base", "selector-split", "selector-ring",
        "selector-provider", "deallocator", "resize-split", "resize-grow",
        "resize-shrink",
    ]
    subject: Literal[
        "initial-block", "selected-block", "split-block", "remainder-block",
        "predecessor-block", "successor-block", "payload-block",
        "released-page",
    ]
    before: _PublicationPrivateArenaBlockState
    after: _PublicationPrivateArenaBlockState
    restoration_role: Literal[
        "none", "initializer-base", "select", "resize", "deallocator",
    ]
    restoration_entry: int | None


@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageRingRole:
    head_slot: int
    provider_entry: int
    inserter_entry: int
    remover_entry: int | None
    provider_calls: tuple[int, ...]
    selector_page_calls: tuple[int, ...]
    selector_request_calls: tuple[int, ...]
    selector_invocations: tuple[_PublicationPrivateArenaInvocation, ...]
    head_reads: tuple[int, ...]
    head_writes: tuple[int, ...]
    ring_link_reads: tuple[int, ...]
    ring_link_writes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaCallEdge:
    caller_entry: int
    call_address: int
    target_entry: int
    edge_kind: Literal[
        "ring", "selector", "deallocator-closure", "mutation-role",
        "resize-context",
    ]
    raw_reconciled: bool


@dataclass(frozen=True, slots=True)
class _PublicationPrivateBlockArenaRole:
    selector_entry: int
    selector_calls: tuple[int, ...]
    deallocator_root: int | None
    deallocator_function_entries: tuple[int, ...]
    deallocator_call_edges: tuple[_PublicationPrivateArenaCallEdge, ...]
    mutation_context_entries: tuple[int, ...]
    mutation_call_edges: tuple[_PublicationPrivateArenaCallEdge, ...]
    block_initializer_entries: tuple[int, ...]
    arena_free_entries: tuple[int, ...]
    splitter_entries: tuple[int, ...]
    unlink_entries: tuple[int, ...]
    insert_entries: tuple[int, ...]
    coalescer_entries: tuple[int, ...]
    resize_entries: tuple[int, ...]
    block_payload_offset: int
    block_page_pointer_flag: int
    block_allocated_flag: int
    block_previous_allocated_flag: int


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaSpan:
    function_entry: int
    instruction_address: int
    operand_index: int
    access: Literal["read", "write", "read-write"]
    region: Literal[
        "page", "page-end", "block", "block-end", "successor",
    ]
    field: Literal[
        "page-link", "largest-free", "extent", "page-end-tag", "sentinel",
        "block-header", "block-page-flags", "block-prev", "block-next",
        "boundary-tag", "successor-header",
    ]
    displacement: int
    width: int


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaTransfer:
    function_entry: int
    role: Literal[
        "ring-insert", "ring-remove", "ring-rotate", "select",
        "block-initialize", "split", "unlink", "insert", "coalesce-prev",
        "coalesce-next", "arena-free", "resize",
    ]
    invocations: tuple[_PublicationPrivateArenaInvocation, ...]
    state_transitions: tuple[_PublicationPrivateArenaStateTransition, ...]
    instruction_addresses: tuple[int, ...]
    span_keys: tuple[tuple[int, int, int], ...]
    function_sha256: str


@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageRingEvidence:
    """Immutable Task 3 ring proof retained by all later arena phases."""

    layout: _PublicationPrivatePageLayout
    role: _PublicationPrivatePageRingRole
    transfers: tuple[_PublicationPrivateArenaTransfer, ...]
    spans: tuple[_PublicationPrivateArenaSpan, ...]


@dataclass(frozen=True, slots=True)
class _PublicationPrivateArenaDependency:
    kind: Literal["function", "global-slot", "absolute-reference"]
    identifier: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _PublicationPrivatePageArenaInvariant:
    allocator_root: int
    factory_entry: int
    page_provider: int
    large_allocator: int
    extent_token_sha256: str
    initializer_effects: _PublicationPrivateHeapEffectClosure
    layout: _PublicationPrivatePageLayout
    page_ring: _PublicationPrivatePageRingRole
    block_arena: _PublicationPrivateBlockArenaRole
    induction_substituted_entries: tuple[int, ...]
    function_entries: tuple[int, ...]
    call_edges: tuple[_PublicationPrivateArenaCallEdge, ...]
    spans: tuple[_PublicationPrivateArenaSpan, ...]
    transfers: tuple[_PublicationPrivateArenaTransfer, ...]
    dependencies: tuple[_PublicationPrivateArenaDependency, ...]
    allocator_dependency_fingerprints: tuple[tuple[int, str], ...]
```

Every operand identity is the triple
`(function_entry, instruction_address, operand_index)`. Call-edge tuples are
replaced with typed rows so call address, owner, target, context class, and raw
reconciliation cannot be confused. Invocation and state-transition rows make
one function's different abstract preconditions and local postconditions
durable.

Allocation and free-list membership are independent facts. Invocation rows
retain each call site's incoming block state; state-transition rows retain the
role/context/subject-specific local postcondition. The stable
combinations at an externally visible arena boundary are `free/listed` and
`allocated/unlisted`. `free/unlisted` is a bounded transient after the
initializer-base block initialization, after selector split initializes `B2`
but before split links it, and inside insert after bit `2` is cleared but before
the block is listed. `allocated/listed` may occur only instruction-locally
inside unlink between setting bit `2` and completing detachment; it is never a
nested-call return or compound-boundary state. Resize split returns `B2` as
`allocated/unlisted`, not `free/unlisted`. Although that is a stable pair, the
resize `B2` row retains a `resize` consumption obligation until insert lists
the remainder; likewise selector `B` remains `free/listed` across split but
retains a `select` obligation until unlink allocates and detaches it.
`none/none` is used when an invocation has no block; mixed `none` states reject.
Canonically ordered transition rows prevent replay from collapsing the two
sequential split calls or their different subjects. Every transition to a
transient, and every stable state that the enclosing compound must still
consume, names its exact restoration role and owner entry; final closure must
prove that owner discharges the obligation before return. A page-only or null
invocation uses `none/none`; its separately proved control-flow return may
still be null without inventing a block-state alternative. For a block-bearing
call, the invocation input state must equal the matching transition's `before`
state.

The initializer effect closure is the unique induction base. There is no
`initialize` value in the ordinary transfer-role literal. Every helper executed
by the initializer and reused after the induction base is instead represented
by its ordinary arena role. `induction_substituted_entries` is the canonical
exact intersection of initializer-effect executed helper entries and arena
transfer entries with at least one non-`initializer-base` invocation. It is
derived as:

```text
effect_executed_helper_entries
& {T.function_entry | any(I.context != "initializer-base" for I in T.invocations)}
```

Exact retail includes at least insert and block initializer; any additional
intersecting helper is included by the same rule. One durable
`block-initialize` transfer binds its helper entry, all three unique call sites,
and five contextual invocations: initializer base plus both ordered split calls
under selector and resize. It retains each `B`/`B2` subject, input bit-2
lineage, local postcondition, function dependency, and exact spans. The insert
transfer likewise binds initializer-base, arena-free, and resize contexts with
complete later-execution spans and proves bit-2 clearing before list insertion.
Exactly one durable
`select` transfer covers the selector body and all of its invocation contexts.
One durable `arena-free` compound transfer binds payload recovery, the
insert-local free/unlisted transient, nested insert/coalesce and
page-removal/release paths,
and restoration at every classified deallocator boundary. Its transfer and
invocation role is `arena-free`, each invocation context is `deallocator`, and
every transient state-transition row names `restoration_role="deallocator"`
and the exact enclosing deallocator entry.

## Layout and Flag Semantics

Layout values are derived from decoded evidence and retained because the
program proves them. Exact retail integration asserts extent alignment
`0x1000`, block alignment `8`, size flag mask `7`, page-pointer flag `1`,
allocated/not-on-free-list flag `2`, previous-allocated flag `4`, and payload
offset `8`. Production does not use those values to select a body and does not
infer that provider result `P` is page-aligned.

Initial layout recovery leaves `page_link_offsets` and
`minimum_split_remainder` null. Ring recovery alone binds the two distinct page
link offsets. Selector recovery alone binds the unique unsigned minimum
remainder. Block-role recovery binds the payload overlay and the three distinct
flag meanings.

The induction base establishes `P+8` largest-free, `P+0xc` as `E | 3`, first
block `P+0x10`, page-end tag `P+E-8`, end sentinel `P+E-4`, block size/page
flags/prev/next at `+0/+4/+8/+0xc`, and boundary tag `B+S-4`. For the initial
block, `S=E-0x18`. The page publisher, not initializer effects, writes page
links at `P+0` and `P+4`.

The block `+8/+0xc` words are a state-dependent overlay. They are reciprocal
free-list links only while membership is `listed`, independently of the
allocation bit. For stable `allocated/unlisted` blocks, payload begins at
`B+8` and those words are client storage. Selector split preserves
`free/listed` `B` and links free `B2` before returning; unlink alone converts
that listed `B` to `allocated/unlisted`. An instruction-local
`allocated/listed` state inside unlink retains link capability only until the
same helper completes detachment. A `free/unlisted` block has no link capability
until the owning splitter or insert transfer lists it. A load does not become a
page, block, size, sentinel, or link capability because its displacement is
familiar. After the exact initializer induction base, every writer of a typed
field must be a certified contextual transfer.

## Structural Role Discovery

Discovery starts from a non-null `_PrivateHeapAllocatorContract`, its exact
extent witness, and its current initializer effects.

1. Use only `contract.page_provider`, `contract.large_allocator`, and
   `contract.factory` as allocator anchors. Do not scan the image for a
   familiar role.
2. Recover the unique page-head slot from the large allocator's nullable page
   source and provider publication destination. Reconcile every overlapping
   writer and exact absolute reference.
3. Recover publisher/remover shapes from provider and deallocator closures.
   Prove null/singleton/nonempty ring behavior and both reciprocal links.
4. For each selector call site, derive a nonempty subset of `provider` and
   `ring` page origins. Require their collective union to contain both. Prove
   that every selector call receives the identical normalized request lineage.
   A site may be a path join; it need not have exactly one origin. Recover and
   serialize a head rotation after successful existing-ring selection. These
   page/request call rows carry `none/none` input block state; Task 4's select
   state transitions describe the conditional selected block.
5. Recover the selector as the unique callee satisfying those complete
   per-site page and request domains. Raw bytes, decoded targets, source/target
   indexes, and least-reachable incoming-call closure must reconcile.
6. Begin deallocation discovery only at `contract.deallocator_root` and close
   its exact outgoing dependency/call graph. From selector and that closure,
   classify block initializer, arena free, split, unlink, insert, and
   coalescers by successful transfer. Block initializer's complete incoming
   inventory must retain the initializer-base call plus both sequential split
   calls under both selector and resize contexts, with input bit-2 lineage,
   `B`/`B2` subjects, and distinct allocation/list-membership postconditions.
   Arena free's
   compound transfer must be rooted in that closed deallocator context and bind
   every nested mutation/release edge before the boundary returns.
7. Close the complete incoming domain of every discovered mutation role. An
   otherwise external owner may enter the mutation fixed point only if its
   complete relevant paths type-check as one bounded `resize` context. Add it
   to `mutation_context_entries`, fingerprint it, and repeat incoming-role
   closure. Do not add arbitrary incoming callers to the deallocator closure.
8. Use `_least_reachable_incoming_call_domain_is_closed` for raw callers so
   owned instruction interiors and finally certified data/residue do not
   become false calls. Final recovery must still reconcile every provisional
   raw site against the exact executable partition.
9. Derive `induction_substituted_entries` from the exact intersection of
   initializer-effect executed helper entries and completed transfer entries
   having at least one non-`initializer-base` invocation.
   Every intersecting active helper requires complete arena spans,
   fingerprints, dependencies, invocations, and transitions. An allowlist of
   block initializer or insert is forbidden; the exact intersection is the
   rule.

Exactly one coherent role graph is required. Missing roles are allowed only
when no certified context needs them. Unknown contexts, conflicting role
assignments, unresolved or indirect mutation edges, an address-taken domain
without complete finite callers, or a fixed-point limit reject the certificate.

## Process-Local Relational Domain

Selector and mutation checking use a bounded, process-local abstract
interpreter. Its value lattice distinguishes at least null, page, tagged
extent, masked extent, page end, sentinel, block, tagged block header, block
size, normalized request, remainder, boundary-tag size, successor header, and
condition. Values carry the exact extent token, same-page relation, independent
allocation and list-membership states, and an interned bounded expression
token. Joins never infer membership from the allocation flag or allocation
from link-shaped words.

Predicates are separate typed facts. They retain unsigned fit, unsigned
minimum-remainder, equality/inequality, nullability, adjacency, and flag tests.
Joins preserve a relation only when every incoming state proves the identical
fact. The only widening is a same-page block recurrence at the certified
circular-list backedge. Unknown predicates explore both successors; an
unsupported value, relation, call context, or state-cap fails closed.

The interpreter distinguishes local helper postconditions from compound
restoration obligations. A nested block-initialize return may carry
`free/unlisted` only for initializer base or selector `B2`, with the exact
initializer/select restoration boundary. Insert may carry `free/unlisted` only
between clearing bit `2` and linking the same block. `allocated/listed` is
bounded to unlink instructions after the bit set and before detachment; no call
return may carry it. Resize split returns `allocated/unlisted`. No transient
can reach another caller, loop backedge, public return, or body-domain handoff.

Arithmetic remains mathematical until a relation proves a concrete 32-bit
interval. Retail coalescers do not branch on carry. Their size sums are safe
because proved adjacency gives `A+T=B` or `N=B+S`, and the existing successor
block bound proves the same final end address. “Checked sum” therefore includes
this relational proof; it does not require an instruction pattern absent from
retail.

The abstract interpreter keeps successor-block-header and page-end-tag cases
separate. Their exact `B+S` operand is serialized as a
`region="successor", field="successor-header"` span only after both variants
are proved: an ordinary same-page block header or the exact `P+E-8` terminal
page-end tag. It never includes the `P+E-4` free-list sentinel.

## Inductive Invariant

For each provider allocation, the certificate introduces `Page(P, E)` tied to
the existing extent token.

The page invariant is:

- `E` satisfies the provider minimum, recovered extent alignment, and no-wrap
  proof; this says nothing about the alignment of `P`;
- page header, first block, page-end tag, and sentinel lie in `[P, P+E)`;
- published page links are reciprocal same-allocator page capabilities, with a
  self-linked singleton and null only while unpublished;
- masking the tagged extent word yields exactly `E`;
- largest-free is zero or at most the usable arena extent.

For `Block(P, E, B, S)`:

- `S` is aligned by the recovered block alignment, and masking the header
  yields exactly `S`;
- `B+S` does not wrap and does not pass the page-end-tag boundary;
- the page/flags word masks to the same `P` with the recovered page-pointer
  flag semantics;
- allocation-flag clear means `free` and set means `allocated`; it does not by
  itself prove list membership. At a compound restoration boundary, a free
  block appears exactly once in the page's reciprocal free ring and an
  allocated block is unlisted with payload beginning at `B+8`;
- between certified nested calls, `free/unlisted` is permitted only for the
  initializer-base block, selector `B2` before split links it, or insert after
  bit-2 clearing, with a unique enclosing restoration obligation.
  `allocated/listed` is permitted only inside unlink and must be gone before
  that helper returns. Membership, not the allocation bit, controls whether
  `B+8`/`B+0xc` may be interpreted as reciprocal links;
- previous-allocated clear proves that `B-4` is the exact boundary tag of an
  adjacent free predecessor; previous-allocated set forbids using `B-4` as a
  predecessor capability;
- the page-end tag acts only as the terminal successor header; the separately
  typed sentinel stores the nullable free-list head;
- every boundary tag is written only at the exact derived end of a certified
  free block.

## Preservation Proof Boundary

The embedded initializer effects establish the induction base. Transfer
checking has two levels. Nested helpers prove exact local postconditions,
including bounded transient states. The enclosing initializer execution,
`select`, resize, or deallocator context is the compound restoration boundary
that must re-establish the full invariant at every externally visible return.
Requiring the full invariant at each nested helper return would incorrectly
reject the retail transitions.

The durable contextual obligations are:

- ring insert/remove/rotate preserve reciprocal page links and exact head
  semantics;
- `block-initialize` has the complete incoming inventory for initializer base
  and both sequential split call sites in both split contexts. It proves the new
  header, page/flags association, size, boundary tag, successor relationship,
  and the allocation value copied from input `B` header bit `2` without
  inventing list membership. The five contextual postconditions are:
  initializer-base initial `B` is `free/unlisted`; selector first-call `B` is
  `free/listed`; selector second-call `B2` is `free/unlisted` until split links
  it; and resize first-call `B` plus second-call `B2` are both
  `allocated/unlisted`. Both selector rows retain the `select` restoration
  owner, and resize `B2` retains the `resize` owner even though its abstract
  state pair is stable;
- the single `select` transfer follows only same-page free-list links, tracks
  and writes largest-free on failure, conditionally splits, writes the exact
  `D` head from the selected block's successor, and enters split with
  `free/listed` `B`. After split returns both `B` and `B2` free/listed, unlink
  sets `B` bit `2`, updates the successor previous-allocation flag, repairs the
  exact `D`, singleton, reciprocal-link, sentinel-head, and `P+8` cases, and
  returns only `allocated/unlisted` `B` or null with the full invariant
  restored;
- split requires `R <= S`, `S-R >= minimum_split_remainder`, and a nonwrapping
  `B+R` at every incoming call. It snapshots input `B` bit `2`, invokes both
  exact `block-initialize` sites sequentially with that allocation value for
  `B` and `B2`, and never treats the sites as mutually exclusive. Free/listed
  selector input causes split to splice free `B2` after `B`; allocated/unlisted
  resize input causes no list operation and returns allocated/unlisted `B2`;
- unlink consumes `free/listed` selector `B`, sets bit `2`, yields
  `allocated/unlisted`, updates the successor-header previous-allocation flag,
  and repairs the exact `D`, singleton, reciprocal-link, sentinel-head, and
  `P+8` largest-free cases. Its instruction-local `allocated/listed` interval
  cannot escape the helper;
- insert consumes either initializer-base `free/unlisted` or structurally
  proved arena-free/resize `allocated/unlisted`, clears bit `2` before any list
  link use, yields `free/listed`, then invokes previous and next coalescing
  before the compound owner updates largest-free. Its
  initializer-base execution is induction evidence; every later arena-free or
  resize execution is covered by the same durable insert transfer and complete
  arena spans;
- coalesce-prev requires the previous-free flag/boundary-tag adjacency and
  removes current `B` while leaving the predecessor as the listed survivor;
- coalesce-next requires `N=B+S`, removes free `N`, leaves `B` as the listed
  survivor, and updates the next successor header or exact page-end tag;
- resize proves both grow and shrink contexts, including request normalization,
  grow-side next coalescing, fit/remainder guards, allocated/unlisted input to
  split, bit-2 preservation by both block-initialize calls, an
  `allocated/unlisted` returned `B2`, insert's bit-2 clear before listing every
  returned remainder, and full restoration before every resize exit;
- the `arena-free` compound transfer starts with an
  `allocated/unlisted` payload block, recovers `B=Q-payload_offset` and `P`
  from the tagged page word, calls insert with `allocated/unlisted` `B`, binds
  insert's bit-2-clear `free/unlisted` transient and subsequent listing/
  coalescing, and then either returns a stable `free/listed` survivor or proves
  the whole-page predicate before ring removal and release to `none/none`.
  Private-free's small and arena branches are mutually exclusive; the small
  path may reach arena-free only through its separately certified backing-page
  retirement call. Every nested call edge, operand span, fingerprint, and
  dependency is bound, and no transient escapes the exact deallocator
  restoration boundary.

The certificate covers allocator metadata accesses. Non-arena branches of a
validated resize context may contain unrelated read-only metadata or hand off
to already certified allocator/deallocator roots, but no unclassified write may
consume or synthesize an arena capability. Every arena-derived memory operand
on every live arena context requires an exact span. Any additional arena write,
partial write, unbounded index, or capability escape rejects the context.

## Publication-Audit Integration

`_publication_body_address_domains` discovers candidate arena bases from the
allocator bridges/contracts, independently of the returning-body list. This is
required because the initializer or provider can be a dependency callee rather
than a returning body. After initializer-effect contexts are available, it
builds each distinct arena invariant at most once in that body-domain call.
The process-local memo key contains the allocator root, the sorted explicit
protected-slot tuple, the contract fingerprint, the extent token, and the
exact initializer effect closure. There is no persistent or replay-bypassing
arena cache.

A function-to-context map makes body lookup constant time. Before operand
authorization, the consumer reconciles the returning closure's call edges
against the invariant's contextual invocation rows, including every
induction-substituted helper, arena-free/deallocator, and resize context. A
missing body rejects only when an active arena transfer edge names it. Any
function in `excluded_functions` that is an arena transfer owner or invocation
context rejects. Block initializer, insert, arena-free, and all other active
transfer bodies therefore receive ordinary span-and-invariant witnesses for
every arena operand outside the original initializer execution.

For a function with any arena context, the consumer scans every memory operand
in the complete body. It does not apply effect-style executed-instruction
pruning and does not skip transfer instructions. A body operand is authorized
only by an exact
`(function_entry, instruction_address, operand_index)` lookup. Its
`_PublicationBodyAddressDomainWitness` stores both:

```python
private_page_arena_span: _PublicationPrivateArenaSpan | None = None
private_page_arena_invariant: _PublicationPrivatePageArenaInvariant | None = None
```

The span is the operand-specific authority; the invariant is its complete
provenance. A plain arena invariant without a span, a span for another operand,
an instruction inventory, or a conflicting contextual span returns `None`.
A simultaneously installed exact effect-span/arena-span key overlap rejects.
Disjoint effect and arena contexts may coexist only when the arena invariant
embeds that exact initializer effect closure. At each body exit, the exact used
arena span-key set must equal that body's certified arena span-key set.

Induction substitution does not weaken that collision rule. For every entry in
`induction_substituted_entries`, its initializer-base execution is replayed as
embedded induction-base evidence but is not installed as a second body-address
authority for the later active helper body. Later block-initialize, insert, and
any other intersecting transfer contexts install only their complete arena
span-and-invariant context. The consumer derives and checks the exact
intersection generically; it does not special-case helper names. If construction
ever attempts to install both an effect context and an arena context for the
same exact helper operand in one body-domain invocation, it rejects instead of
choosing one by precedence.

## Serialization and Dependency Replay

The invariant is durable evidence, not a process-local inference. Construction
canonicalizes and rejects duplicates before publication:

- embed the exact current initializer effect closure;
- require exactly one `select`, one coherent `arena-free` compound transfer,
  and no ordinary `initialize` transfer;
- sort contextual invocations, state transitions, typed edges, triple span
  keys, spans, transfers, `induction_substituted_entries`, and role entries;
  reject duplicate/conflicting keys;
- snapshot every function, concrete global slot, and exact absolute reference
  as canonical `_PublicationPrivateArenaDependency` rows;
- copy the allocator dependency fingerprint tuple exactly from the extent
  witness into the invariant; and
- fingerprint every ring, block-initializer, insert, arena-free, transfer,
  deallocator, incoming-context, and resize owner.

Replay has one fail-closed ordering:

1. Validate immutable shape, canonical ordering, unique keys, and closed
   literals without noting or trusting any row.
2. Replay allocator dependency fingerprints and the embedded initializer
   effects with their existing current-evidence validators.
3. Replay canonical function/global-slot/absolute-reference dependency rows,
   raw/decoded/provisional-residue call closure, contextual incoming calls, and
   exact function fingerprints.
4. Freshly recompute layout, ring, selector, every induction-substituted helper,
   both ordered block-initializer calls in every split context, input bit-2
   lineage, insert clear-before-list postconditions, the private-free
   small/arena branch partition, arena-free and resize compound restoration
   obligations, mutation contexts, typed edges, transfers, and spans with no
   arena memo lookup.
5. Require exact dataclass equality between the freshly assembled invariant
   and the supplied invariant.
6. Only after equality succeeds, propagate/note its dependencies and permit an
   operand-specific consumer to use its span.

There is no persistent or replay-bypassing independent arena cache. The local
body-domain construction memo may deduplicate identical proof inputs within one
call, but a later durable cache must store the whole immutable invariant and
replay this same sequence.

## Fail-Closed Hostile Matrix

Each hostile changes one fact while retaining the surrounding valid graph. The
certificate rejects:

- a selector site with an empty or foreign page origin, collective origins
  missing provider or ring, adjusted provider result, changed request lineage,
  extra selector caller, missing rotation, or rotation of a different page;
- a foreign/partial/indexed page-head writer, broken singleton, missing
  reciprocal page link, stale absolute-reference dependency, or unresolved
  ring edge;
- changed extent/size mask, sentinel or page-end off-by-one, missing
  largest-free initialization/update, or a post-initializer extent clobber;
- selector recurrence through a foreign page, successor/page-end type
  confusion, unknown loop branch, missing fit guard, missing minimum-remainder
  guard, wrong failure largest-free value, or omitted select invocation;
- missing/stale block-initializer entry, call site, invocation, dependency,
  span, or transfer; either split initializer call skipped, reordered, or made
  context-exclusive; either allocation argument not copied from input `B` bit
  `2`; `B`/`B2` subjects collapsed; inferred membership from the allocation
  bit; a selector first/second result other than `free/listed` and then
  `free/unlisted`, a resize first/second result other than
  `allocated/unlisted`, or a missing/retargeted compound restoration owner;
- a missing/stale insert initializer-base or later invocation, missing insert
  arena span/dependency/transition, incomplete
  `induction_substituted_entries`, an entry not in the exact effects/transfer
  intersection, or an installed exact effect/arena key collision for either
  insert or block initializer;
- split on `R>S`, too-small remainder, wrapping `B+R`, selector input not
  `free/listed`, selector `B2` not linked before split return, resize input or
  returned `B2` not `allocated/unlisted`, a fabricated resize
  `free/unlisted` remainder, or a transient escaping its unique compound
  restoration boundary;
- unlink that does not consume `free/listed` `B`, set bit `2`, detach to
  `allocated/unlisted`, update the successor previous-allocation bit, or cover
  exact `D`/singleton/reciprocal/`P+8` cases; insert that does not clear bit `2`
  before listing an allocated/unlisted input; either helper with foreign links,
  partial metadata writes, wrong sentinel transition, coalescing before
  insertion, or an arbitrary block/page argument;
- previous coalescing without the previous-free flag and exact boundary tag,
  next coalescing without exact adjacency, removal of the wrong survivor,
  successor-header/page-end confusion, or a relationally unproved sum/overrun;
- resize without a complete incoming domain, foreign payload, wrong `Q-B`
  offset, changed page-pointer flag/mask, missing grow coalesce, missing fit or
  remainder guard, omitted returned-remainder insert, or an unclassified write;
- a missing/duplicate arena-free role, entry, invocation, or transfer; arena
  free without an exact allocated-payload input; missing
  insert-local `allocated/unlisted -> free/unlisted -> free/listed` ordering,
  private-free allowing both or neither direct small/arena branch, small payload
  reinterpreted as direct arena payload, insert/coalesce before/after order
  changed, transient escaping a deallocator return, whole-page release
  without the exact single-usable-block predicate, page removal/release in the
  wrong order, or missing arena-free body/call/span/fingerprint/dependency;
- a live mutation-role caller that cannot be classified as selector,
  initializer, deallocator, or bounded resize; a raw caller that does not
  reconcile as owned code/data/residue; or an unresolved indirect role edge;
- stale/missing/duplicate invocation or state transition, typed edge, triple
  span key, function, global-slot, absolute-reference, allocator,
  initializer-effect, layout, or extent-token evidence;
- an ordinary initialize transfer, missing/duplicate `block-initialize`
  transfer, missing/duplicate `arena-free` compound transfer, zero or multiple
  select transfers, a nested transient falsely classified as already stable,
  failure to enforce stability at its compound return, fresh recomputation
  unequal to serialized evidence, an operand used without its exact span, or a
  certified span left unused by its body.

## Validation Gates

1. Focused synthetic RED/GREEN tests cover the coherent fixture, role
   discovery, induction base, exact generic substitution of insert and shared
   block initializer, positive and hostile exact-key collision behavior, all
   four allocation/membership combinations at their exact stable or
   instruction-local boundaries, both sequential split initializer calls with
   bit-2 preservation, selector unlink and resize insert correction, nested
   local postconditions, the mutually exclusive private-free branches, the
   arena-free retained-page and page-release compound paths, selector, every
   invocation context, resize, Task 6 fresh dependency/compound-transfer replay,
   and Task 7 operand-specific body use and installed-collision rejection.
2. Existing publication/private-heap tests, `py_compile`, Ruff, and
   `git diff --check` pass.
3. Extend only the ignored hydrated diagnostic's existing
   `--private-heap-extent` output. The exact mini-query identifies selector
   contexts, page-head slot, rotation, full mutation/resize graph, contextual
   calls, and certified spans in under two minutes.
4. Run full root `0x435620` only after local and mini-query gates. The later
   `0x435a8c` root and clean Task 7 replay remain parent-plan gates.

## Non-Goals

- No retail-address, owner, caller-count, constant, symbol-name, or byte-string
  selector.
- No generic `private-heap + offset` permission.
- No client-payload correctness proof or arbitrary allocator recognition.
- No weakening of protected-slot, image-capability, reference-disjointness,
  raw-control-flow, or initializer-effect checks.
- No full-root replay while developing an individual transfer rule.
