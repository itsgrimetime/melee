# Return-Path Publication Noninterference Design

## Goal

Allow the object-tag lifecycle proof to cross one otherwise conservative
pointer publication only when every synchronous execution that can return to
the later field observation proves that the publication cannot expose a
mutation of the observed object generation.

This is a lifecycle-only refinement. The ordinary MOVZX producer remains
`movzx-producer-analysis-v27`. The object-tag lifecycle semantics advance from
`object-tag-lifecycle-analysis-v5` to
`object-tag-lifecycle-analysis-v6`. The existing lifecycle certificate schema
and query shape remain unchanged; v6 changes the proof meaning and therefore
the query identity.

## Motivation and retail witness

The current lifecycle proof correctly rejects stores of a tracked pointer to
non-stack memory. That fail-closed rule blocks the retail store at `0x435628`,
which publishes the current object in global slot `0x587130`, even though the
only same-generation path from that publication to the field observation at
`0x43576b` is closed and noninterfering.

The exact retail witness is:

- publication `0x435628 -> [0x587130]`;
- same-generation slice
  `0x435628, 0x43562e, 0x435632, 0x435637, 0x43563c, 0x435642,
  0x435740, 0x435744, 0x435748, 0x43574e, 0x435751, 0x435756,
  0x435757, 0x43575a, 0x43575b, 0x43575c, 0x435761, 0x435765,
  0x435768, 0x43576a, 0x43576b`;
- one in-slice call, `0x43575c -> 0x436470`;
- observation `0x43576b` through the same `EDI` object identity; and
- all other switch arms converge at `0x435a86/0x435a87`, call `0x4c1850`,
  advance `EDI` at `0x435a8c`, and then exit or begin a newly published
  generation at `0x435628`.

These addresses are integration expectations, not production allowlists. The
certificate is derived from instruction bytes, CFG ownership, pointer states,
call targets, PE imports, relocations, and the checked backend session.

## Scope and non-goals

The certificate reasons about the analyzer's sequential, synchronous
call/return model. It does not prove safety against another compiler thread,
signals, APCs, or external asynchronous code that independently reads compiler
globals. No such edge is represented in the current whole-PE control model.

The certificate does not:

- weaken the normal pointer-publication rejection outside an object-tag
  lifecycle evaluation;
- change v27 producer queries, results, checkpoints, or dependency meaning;
- infer a domain from relocation length;
- treat a copied value as nonescaping merely because it is not dereferenced;
- trust arbitrary imports, unresolved indirect calls, or address syntax;
- add a retail-address exception; or
- solve the independent ESP-slot binding failure at `0x4b1f95`.

In particular, the retail value copied to `0x587ffc` is an escape. It is
accepted only as an opaque copy whose derived value is neither dereferenced nor
used as a mutation receiver on a path relevant to the observation. The proof
must never describe that behavior as "no escape."

## Lifecycle-only evaluation context

`_ObjectTagLifecycleQuery` intentionally contains a shared dispatch-family
identity, not one semantic caller or runtime compiler session. Its
`function_entry` is currently the minimum consumer entry and must never be used
as the caller of a publication certificate.

A v6 lifecycle evaluation therefore converts each persisted consumer tuple to
one typed `_ObjectTagLifecycleConsumerBinding` and installs a separate
`_ObjectTagLifecycleEvaluationContext` around that binding's trace. The context
contains the exact query identity, complete typed binding, and
`consumer_entry=binding.function_entry`, where `function_entry` is decoded
from persisted `binding[0]`; it does not assert a backend root or allocator
session. The publication instruction owner and certificate
`caller_entry` must both equal that active `consumer_entry`. A mismatch is
bottom.

The two preservation routines that currently reject pointer publication may
consult the new proof only while this context is active:

- `_pointer_definition_preserves_field_before`; and
- `_function_argument_preserves_field_before` when
  `reject_pointer_publication=True`.

All other callers retain the current rejection. Preservation and publication
memo keys include the active lifecycle query identity, the complete typed
consumer binding, and `consumer_entry`, so a positive answer from one consumer
cannot be reused by a producer query, another lifecycle family, or even another
consumer in the same shared query. Context push/pop occurs inside the binding
loop, is guarded by `try/finally`, and must be stack-exact.

The publishing consumer need not be the minimum binding. A required positive
test places a nonpublishing consumer at the minimum entry and proves a later
consumer can publish only under its own context. The test also proves that
substituting `query.function_entry` for that later caller returns bottom.

When either routine sees a full-width store of a tracked root to non-stack
memory, it asks for a
`_ReturnPathPublicationNoninterferenceCertificate`. Bottom preserves the
current rejection; a certificate excuses that store only. Every other write,
call, alias, and publication check remains active.

## Typed certificate identity

The proof uses frozen typed witnesses rather than positional tuples or strings
whose fields must be guessed by consumers:

- `_ObjectTagLifecycleConsumerBinding` names the consumer entry, MOVZX
  address/bytes/registers, transfer address/bytes, and argument-zero push
  address/bytes. The persisted query remains the existing tuple schema, with
  explicit encode/decode at the checkpoint boundary.
- `_PublicationFunctionBody` binds a returning function entry, its declared
  body range, exact owned byte intervals, and an owned-instruction digest.
- `_PublicationCallEdge` names source, target, direct/finite/import kind, and
  whether the edge can return to the relevant continuation.
- `_PublicationRepublishCut` names the store, old and new root-generation
  identities, distinct-generation provenance, and the exact alias-death
  witness proving no old identity survives the cut.
- `_PublicationTaintOrigin` names the in-slice call, argument index, source
  instruction, source kind, exact root field path, and width.
- `_PublicationTaintFlow` names its origin, instruction, operation, source and
  destination storage identities, and width for every interprocedural copy,
  reload, comparison, or rejected dereference/mutation.
- `_PublicationOpaqueCopyDestination` binds an origin to the exact store
  instruction, destination kind, absolute slot or owned object field, owner,
  offset, and width. It is explicitly an escape witness.
- `_PublicationReferenceRow` is query-independent raw evidence. It binds only
  a type-3 relocation whose loader-initialized value is the protected slot, or
  one decoded literal immediate/displacement/absolute-memory/LEA operand whose
  value is exactly that slot. It records the exact operand span/bytes,
  relocation type, literal source class, protected target slot, and exactly
  one current ownership classification: owned instruction with owner/range,
  typed data with region/provenance, or provisional unowned executable bytes
  with exact containing interval and hash. It contains no arithmetic chain,
  address domain, or closure-relative safety boolean.
  `_PublicationReferenceInventory` contains every row, the ownership/data and
  recovery revisions under which they were classified, the current ownership
  digest, and its canonical SHA-256.
- `_PublicationReferenceDisjointnessWitness` is certificate-local. It binds
  one inventory row to one complete returning `_PublicationFunctionBody` and
  records the exact span relation to both the body's declared range and every
  owned interval. A successful certificate has a disjoint witness for every
  inventory-row/body pair; an overlap or missing pair is bottom.
- `_PublicationBodyAddressDomainWitness` is certificate-local. For one
  returning function body it binds the exact instructions participating in a
  finite arithmetic address-materialization chain, or the instruction that
  introduces an otherwise unknown mapped-global domain; its typed input and
  output address domains; the relation of that domain to the protected slot;
  and the exact function dependency fingerprint under which the body was
  analyzed. A finite domain containing the slot, or an unknown mapped-global
  domain that may contain it, is bottom.
- `_PublicationFinalReferenceEnvironment` binds the post-install control-flow
  and seed revisions plus canonical relocation-classification, typed-data,
  padding, and executable-complement digests. A
  `_ReproducedPublicationTableHypothesis` joins the tentative hypothesis,
  installed table, this final environment, and the post-install
  `_DependencyMemoEntry`; no pre-install certificate has this status.
- `_PublicationImportWitness` binds the call, parsed IAT VA, exact DLL, lookup
  mode (`name` or `ordinal`), name, ordinal, hint, semantic effect, and typed
  `_PublicationImportArgumentEffect` rows for argument index, origin, alias
  class, and permitted effect.
- `_PublicationBackendBridge` binds the exact consumer caller, typed incoming
  `_PublicationIncomingCall` rows for source, raw/decoded kind, owner, and
  reconciliation, the allocator-totality certificate, one backend root, and
  that root's complete closure as typed `_PublicationFunctionBody` rows.

The internal `_ReturnPathPublicationNoninterferenceCertificate` contains those
typed witnesses and also binds:

- compiler SHA-256, lifecycle semantics, summary-fact signature,
  control-flow revision, producer-seed revision, and absolute-write revision;
- lifecycle query SHA-256 and the complete active consumer binding;
- caller entry, root kind and definition, publication instruction and exact
  destination slot, observation instruction, and observed byte interval;
- the exact same-generation instruction slice and typed republish cuts;
- every returning function body, typed call edge, and finite candidate target,
  including targets later pruned by a context-bound proof;
- all typed taint origins/flows and opaque-copy destinations;
- the query-independent complete reference inventory rows/digest and the
  separate complete closure-relative disjointness relation;
- the certificate-local per-body address-domain/materialization witnesses,
  each bound to its returning function dependency;
- every typed import witness and argument effect; and
- every complete backend bridge and closure used to prune failure paths.

Lookup and bottom memo keys contain only structural inputs available before
the proof runs: compiler/query identity, active binding and consumer, caller,
publication/slot, root identity, observation/field interval, analysis limits,
and current recovery/ownership revisions. They never contain slice, closure,
inventory, or other witness digests produced by the computation. A successful
`_DependencyMemoEntry` stores all memoized typed proof evidence, including the
complete certificate, in `.result`. Its `.dependencies` field contains only
canonical `(kind, identifier, fingerprint)` rows for functions, global slots,
and lifecycle-only absolute references. A hit validates those dependency
fingerprints and revisions before replaying the full dependency rows into the
outer lifecycle collector.

## Same-generation path proof

For publication `P`, slot `S`, observation `O`, and tracked root `R`, the
certificate builds the exact instruction set that is both reachable from `P`
and able to reach `O` without crossing a valid republish cut.

The proof requires all of the following:

1. `P` is one owned, pointer-width store to one exact mapped writable absolute
   slot `S`. Its source has the singleton relative-pointer identity `{R + 0}`.
2. `O` observes the requested field through the same dynamic root identity.
   A pointer copy is allowed; a different definition, child offset, partial
   identity, or merged unknown identity is bottom.
3. No edge enters the interior same-generation slice without passing through
   `P`. Every path from `P` that can reach `O` is enumerated.
4. A later write to `S` is a cut only when both conditions hold: the republished
   value has a closed origin proved to be a distinct new generation, and no
   register, stack slot, local/global copy, child, or call-return alias remains
   live with the old generation identity. Killing or advancing the original
   root register alone is insufficient. Rewriting the same root, an unknown
   root, or a nominally new root while a stale old-root alias survives is not a
   cut.
5. Paths that terminate do not need a returning effect proof. Paths that
   satisfy both republish conditions are checked again as a new generation.
   Ordinary writes and calls before the cut remain subject to the existing
   preservation analysis.
6. Apart from `P` and certified new-generation cuts, the slice neither reads
   `S`, writes it, takes its address, nor materializes an address that may equal
   it.

This makes the retail switch structure a consequence of the generic proof:
only the `0x435740` arm remains in the `0x435628 -> 0x43576b` generation; the
other arms terminate or advance before republishing.

A hostile test kills the original root register but preserves the old identity
in a stale alias and republishes through that alias. It must remain in the old
generation and return bottom.

## Returning direct/finite closure

Calls are relevant only if their continuation can still reach `O` in the same
generation. Starting from those calls, the proof computes a bounded fixed
point over internal direct targets and already certified finite indirect target
sets. It includes a callee instruction only when that instruction can reach a
return to its relevant caller. A syntactic tail after a proved nonreturn is not
included.

Every possible returning target must be owned and finite. An unresolved
indirect call, internal target escape, unowned call target, open recursive
reentry to the lifecycle caller, or analysis-limit hit returns bottom. Finite
targets that are contextually impossible remain recorded as candidate target
dependencies before they are pruned.

For retail, the owned direct returning closure rooted at `0x436470` contains
these 39 entries:

```text
0x403d90 0x403db0 0x403dd0 0x403e30 0x403ed0 0x403f60 0x403fd0
0x404020 0x4040e0 0x404180 0x404220 0x4042a0 0x4042f0 0x404400
0x4044e0 0x404610 0x406480 0x4128f0 0x412990 0x4129c0 0x412a50
0x412a90 0x4138b0 0x4138c0 0x413950 0x413990 0x413a00 0x413a40
0x436470 0x441fa0 0x4422f0 0x443110 0x443120 0x4431a0 0x49d140
0x49d170 0x49d1b0 0x49d240 0x4a24e0
```

The finite indirect call at `0x44235b` through slot `0x57fdd4` has candidate
targets `0x41e960` and `0x445760`. Both candidates and their target facts are
dependencies. The session proof establishes that the exact backend invocation
installed `0x445760`; its `0x41b390` context restore with context `0x5841f8`
does not return. In the canonical retail CFG, the independent direct closure
rooted at the session-impossible default target `0x41e960` contains 56 owned
functions. That count is an integration witness, not an acceptance rule. The
analyzer binds `0x41e960` as a finite candidate and excludes its 56-function
closure only through the exact callback-slot/session proof. It prunes only the
session-impossible target and the context-restoring failure path, and checks
every path that can actually return to `0x435761`.

## Protected references and address materialization

The proof inventories all raw literal references to protected slot `S` before
claiming that the returning closure cannot observe it. The canonical inventory
includes every type-3 relocation whose loader-initialized value is `S`, and
every decoded literal immediate, displacement, absolute-memory, or LEA operand
whose decoded value is exactly `S`. Each row binds the operand's exact byte
span and bytes, relocation/source facts, literal source class, and current
query-independent ownership classification. The three ownership classes are
owned instruction, typed data, and provisional unowned executable bytes. The
last class carries the exact current complement interval and byte hash; it is
not accepted residue and conveys no Ghidra fact. Finite arithmetic
materialization chains are deliberately absent from this raw inventory.
The inventory has one canonical row per exact span/target. A decoded operand
that is also the carrier of a type-3 relocation is the same row with
`reference_class="type-3-relocation"`, not a second decoded-literal row;
conflicting spans or classifications are bottom.

This distinction is required by the actual pipeline. Lifecycle recovery runs
inside `_DirectCfgRecovery.recover()`. The final
`UnreachableExecutableResidue` is built only after ordinary ownership reaches
its fixed point, and `accepted=True` is set still later by
`backend_lifetime_audit.accept_reconciled_residue()`. A lifecycle proof must
never read or assume that post-CFG accepted state. Doing so would be circular
and, during certificate construction, impossible.

`_producer_dependency_fingerprint("absolute-reference", S)` therefore hashes
only the complete query-independent raw inventory: sorted reference spans and
bytes, relocation type, literal source class, target facts, exact owner/range,
typed-data region/provenance, or provisional executable
interval/hash, plus the ownership/data, control-flow, producer-seed, and
absolute-write revisions. It does not hash a returning closure or an
`outside_returning_ranges` boolean. The same slot can consequently share one
durable dependency fingerprint across bindings while each internal certificate
checks its own closure.

`reference_classification_revision` advances only when instruction ownership,
declared ranges, typed-data boundaries, relocation classification, or decoded
literal operand classification can change a raw row. Finite arithmetic or
materialization-domain changes do not advance it; their enclosing function
dependency invalidates the certificate-local witness instead.

The certificate separately constructs the full cross-product relation between
inventory rows and returning bodies. Every row span must be disjoint from both
the declared range and all owned intervals of every returning
`_PublicationFunctionBody`; a typed
`_PublicationReferenceDisjointnessWitness` binds each comparison. Any overlap,
straddle, ambiguous source class, or incomplete row/body pair is bottom.
Positive and negative fixtures place the same provisional unowned executable
reference respectively outside all returning ranges and across a returning
range.

The certificate then analyzes finite arithmetic/materialization chains and
unknown mapped-global address domains separately inside each returning body.
Every analysis result is a typed `_PublicationBodyAddressDomainWitness` bound
to that body's current `("function", function_entry, fingerprint)` dependency.
Within the returning closure, a raw literal reference to `S`, a finite domain
that contains `S`, or an unknown mapped-global domain that may contain `S` is
bottom. Stack, fresh heap, and proved object identities remain disjoint from
mapped compiler globals. These body-local witnesses are not part of the
absolute-reference fingerprint and are rebuilt whenever their function
dependency changes.

A lifecycle-v6-only `absolute-reference` dependency fingerprints the raw
inventory. The lifecycle checkpoint decoder accepts that dependency only for a
v6 lifecycle query; v27 producer certificates neither emit nor accept it. The
internal certificate, not the durable dependency row, binds typed bodies and
their complete disjointness and address-domain relations. The certificate
envelope already binds the exact compiler SHA-256.

### Tentative publication-table fixed point

Publication proof cannot install its own control-flow premise. The first
producer pass may validate lifecycle domain bytes and compute a candidate
publication certificate against the already-owned graph, but it must not add a
`JumpTable`, table edges, ownership, or target `SeedRecord`s. In the current
pipeline, `_object_tag_lifecycle_guard_for_index` runs before
`_recover_indexed_table` reads the entries, so the preservation helper cannot
possibly construct table target records. It returns only typed proof evidence
or bottom.

After `_recover_indexed_table` has independently checked the table bounds,
type-3 relocation rows, raw entry bytes, executable targets, and termination,
that table-recovery layer may emit one tentative
`_PublicationTableHypothesis`. The hypothesis binds the transfer/table shape,
entry bytes digest, exact target `SeedRecord`s, structural lifecycle candidate
identity, and no installed table state. That candidate identity excludes
ownership/seed/recovery revisions that intentionally change when targets are
seeded; the publication memo lookup key separately adds those revisions.
Recovery returns unresolved for that transfer on this pass.

Publication admission has three ordered stages:

1. **Baseline hypothesis.** Baseline recovery validates the lifecycle shape
   and table bytes, constructs target records, and emits the non-mutating
   tentative hypothesis described above. A pre-install certificate may screen
   whether a trial is worth attempting, but it is provisional: target seeding
   adds no candidate table edge, and installing the table later increments
   `control_flow_revision`, so the pre-install certificate is necessarily
   stale and can never reproduce the hypothesis by itself.
2. **Disposable installation trial.** The outer replay creates a new recovery
   from authoritative seeds plus the hypothesis target records and passes the
   candidate identity separately. Seed presence alone installs no edge. When
   this disposable recovery reaches the exact table, `_recover_indexed_table`
   may install the table, edges, data evidence, and finite targets
   provisionally, increment the control-flow revision, enqueue its targets,
   and run the ordinary closure to quiescence with those installed edges. No
   result from this mutated trial is reusable yet. Publication trials use
   private producer/finite memo maps; only entries validated by stage 3 may be
   merged into outer in-memory caches. Dependency-bound durable checkpoint
   files may remain, but they confer no graph ownership.
3. **Definitive post-install validation.** After the installed-edge closure is
   quiescent, recovery finalizes relocation classification, seed provenance,
   typed-data and padding boundaries, and the current executable complement.
   It then explicitly recomputes lifecycle v6 under every exact binding against
   the installed graph and finalized reference environment. Only this fresh
   post-install certificate and dependency snapshot mark the hypothesis
   reproduced and may contribute `RawCfg` certificates or obligations.

If definitive validation returns bottom, changes identity, or sees any stale
dependency, the trial marks the candidate unreproduced. The outer loop discards
the entire mutated recovery and rebuilds without that candidate; it must never
return, retain as `reusable_trial`, or otherwise reuse the failed graph. A
changed table byte, target record, candidate identity, normalization revision,
fingerprint, aggregate result, or certificate witness has the same outcome.
The final invariant is stronger than hypothesis membership: every
publication-dependent `RawCfg` table has a current post-install certificate
whose stored dependency fingerprints validate against that exact finalized
recovery.

### Final normalization and checkpoint ordering

The existing pipeline performs dependency-affecting work after ordinary
producer recovery: `_classify_relocations()`,
`_bind_seed_instruction_provenance()`, `_merged_data_regions()`,
`_padding_regions(...)`, ownership-disjointness validation, and
`_provisional_unreachable_residue(...)`. In particular, seed provenance binding
increments `producer_seed_revision`. Definitive publication validation runs
only after those operations have fixed relocation source classes, seed bytes,
typed-data/padding boundaries, and the exact current executable complement.
Recovery snapshots the resulting revisions and reference-environment digests;
any change during or after definitive validation restarts the disposable trial
or rejects its candidate before `RawCfg` construction.

The definitive recomputation uses the normal
`_ProducerCertificateSession.evaluate` path under the exact lifecycle query.
Its installed graph and finalized environment can produce a second file with
the same query SHA-256 but a new dependency SHA-256. That is the intended
query-bound dependency variant. It is subject to the normal query-budget and
fresh-resume gate. If the recomputation checkpoints new work and requires a
fresh resume, the mutated trial is discarded; the resumed run rebuilds it and
rehydrates/validates the post-install variant before reproduction. A finite
pre-install checkpoint or dependency snapshot is screening evidence only and
is never treated as the final lifecycle certificate.

### Ownership and external-reconciliation gates

A provisional reference can support only a tentative publication-table
hypothesis while ordinary ownership is growing. Each hypothesis records the
raw inventory digest, ownership digest, recovery revisions, table bytes, and
target records. The disposable trial recomputes the inventory, complete
body-disjointness relation, and body address-domain witnesses after installing
the table, closing its edges, and finalizing all dependency-affecting
normalization. Ownership or normalization growth invalidates its earlier
memo/dependency entry. Recovery may recompute under the new owner/range; if the
row now overlaps a returning body or cannot be classified exactly, the
hypothesis and its jump-table admission are rejected. No pre-install
certificate is retained merely because the original owner register or context
has gone out of scope, and no pre-install certificate is serialized as audit
evidence.

A definitive post-install row may still be only provisional unowned executable
evidence. The returned `RawCfg` carries exactly the canonical union of
provisional-reference obligations from every definitive post-install
certificate to the existing external Ghidra/residue audit. The crosscheck
digest binds that exact obligation set. Final bundle publication requires the
audit to reject
missing, extra, or stale results, reconcile every obligated
span/byte/classification, and
`accept_reconciled_residue()` to bind the resulting reconciliation SHA-256.
Missing, conflicting, or rejected reconciliation makes the report
unpublishable. An accepted serializer emits exactly one consolidated
`return-path-publication-noninterference` audit row; absence of that row is an
error. The audit does not make the earlier closure-disjointness proof; it only
accepts or rejects the provisional source classification.

Retail has no direct or materialized `0x587130` reference in the returning
closure. Its complete raw inventory has 19 relocation sites, including six
provisional executable sites at `0x4a1cc2`, `0x4a1ccb`, `0x4a1d10`,
`0x4a1d19`, `0x4a1db4`, and `0x4a1dbd`. The internal certificate proves those
spans lie outside all 39 returning bodies. All six are bound to containing
interval `[0x4a1caa, 0x4a1dd0)` with byte SHA-256
`ad98fc322eda4028deb382fe6c3f844e70bab2b747d5b620088ad6e7bd8903a0`;
the final audit must independently bind each full row to the current residue
reconciliation SHA-256 before publication.

## Actual-value effects

At each in-slice call, relative-pointer state first proves that no actual is
the protected root, a child of it, or the address of the publication slot. A
slot address passed directly or through a materialization/copy chain is bottom.
Values loaded from fields of the root are then tracked as opaque actual taints
through register, stack, field, and global copies across the returning closure.

An opaque taint may be copied, stored into an unrelated object/global slot,
compared, masked, or tested. It may not:

- appear as a memory base or index;
- be dereferenced, used as a write receiver, or used to materialize the
  protected root/slot;
- be forwarded to an unresolved target; or
- cross the import boundary unless that exact imported contract accepts the
  corresponding scalar argument.

For the retail call at `0x43575c`, the three actuals are derived from
`[EDI+0x16]`, the zero-extended word `[EDI+8]`, and the boolean
`([EDI+6] & 0x10) != 0`. None is the root, a child pointer, or a slot address.
`0x436470` copies values to manager fields and copies the first actual loaded
from `[EDI+0x16]` to `0x587ffc`; it does not dereference or mutate through those
actual-derived values. The `0x587ffc` store is recorded as a typed accepted
opaque-copy escape with its origin and destination.

Taint propagation continues after stores: reloading an escaped value from an
unrelated global or object field remains the same typed origin. A required
hostile test copies an actual through two storage hops, reloads it, and then
dereferences or mutates through it; the proof must reject the final effect.

## Exact system-import trust boundary

The closure may cross only imports whose exact parsed `pe.Import` row and
semantic effect contract match. A witness binds DLL, IAT VA, hint, and exactly
one lookup mode: `name` with nonempty `name` and `ordinal=None`, or `ordinal`
with `name=None` and a concrete ordinal. Name and ordinal modes are never
interchangeable. The retail witness uses only:

- `KERNEL32.dll!EnterCriticalSection` at IAT `0x57a168`;
- `KERNEL32.dll!LeaveCriticalSection` at IAT `0x57a16c`;
- `KERNEL32.dll!GlobalAlloc` at IAT `0x57a190`;
- `KERNEL32.dll!GetLastError` at IAT `0x57a178`; and
- `KERNEL32.dll!GlobalFlags` at IAT `0x57a1e4`.

The synchronization contracts may mutate only their supplied critical-section
object, which must be proved disjoint from the protected root, slot, and opaque
actual taints. Allocation accepts scalar flags/size and returns fresh external
storage. The two query functions consume no protected compiler pointer. A
same-named symbol from another DLL, an ordinal/name mismatch, a changed IAT VA,
an unlisted import, an extra tainted argument, or a synchronization/handle
actual that aliases the protected root, slot, or opaque taint is bottom. The
import contract is an explicit trust boundary, not a deduction that arbitrary
system calls are pure.

In production, the trust anchor is the strict PE parser's `Import` row together
with the exact compiler SHA already bound by the certificate. The lifecycle
proof does not claim to reparse raw import-directory bytes. Tests that only
construct or mutate `Image.imports` exercise semantic matching, not raw-PE
integrity. Ordinal/name and changed-IAT integrity tests therefore use a raw PE
fixture, parse it through the strict public `pe_mod.load(...)` entry point, and
then run recovery on the returned `Image`.

## Allocator failure and backend-context bridge

Allocator failure is pruned only by the existing context-bound
`_AllocatorTotalityCertificate`. The publication proof discovers the owned
bump allocator and allocation caller from the returning closure, requests a
totality certificate with the lifecycle caller included in `lifetime_roots`,
and accepts a nonreturn callback only when that certificate binds the checked
session, callback installation, setjmp/context restore, backend root, reset
exclusion, and complete lifetime closure.

This is not sufficient by itself. `_ObjectTagLifecycleQuery` has no session
context, so v6 adds an explicit bridge:

1. Set `lifecycle_caller` to the active binding's `consumer_entry`, require the
   publication owner and certificate caller to equal it, and then require
   `_incoming_call_domain_is_closed(lifecycle_caller)`. The strict
   proof, not the least-reachable provisional fallback, must reconcile raw E8
   sites with decoded calls, exports, type-3 address-taken references, and
   finite indirect callers.
2. Enumerate every exact `_incoming_call_sites(lifecycle_caller)` row and map
   each source to its exact owning function. Missing or ambiguous ownership is
   bottom.
3. Require one backend root from the totality certificate whose exact direct
   closure contains the lifecycle caller, the allocation caller, and every
   incoming owner. Membership of the allocation caller alone is explicitly
   insufficient, and the union of two backend closures cannot substitute for
   one root that contains the complete required set.
4. Bind the raw caller reconciliation, owners, backend root, and complete
   backend closure as certificate fields and function dependencies.

For retail, `_incoming_call_domain_is_closed(0x4351c0)` must prove exactly the
three raw/decoded calls at `0x50e976`, `0x50f09d`, and `0x50f96b`, owned by
`0x50e850`, `0x50ee60`, and `0x50f8b0`. All three owners, `0x4351c0`, and
`0x436470` must lie in the certified `0x48b6c0` backend closure. The exact
session is rooted at `0x43edb0`, initialized by `0x4421c0`, grows through
`0x4422f0`, installs callback `0x445760` in `0x57fdd4`, saves context with
`0x41b370`, and restores it with `0x41b390`.

Callback-slot stability covers every overlapping byte. A partial one- or
two-byte write to `0x57fdd4..0x57fdd7` invalidates totality just like a full
overwrite. Hostile fixtures cover both a partial overwrite and a split backend
where only the union of two roots contains all incoming owners.

## Allocator-totality dependency replay

The current allocator-totality cache returns a cached certificate before
re-noting the dependencies that were noted on the original construction. A
nested lifecycle proof can therefore persist an incomplete dependency set.

Successful allocator-totality cache entries become dependency-bearing memo
entries. Their snapshot contains:

- allocator and allocation caller;
- session root and initialization target;
- every backend root and every function in each backend closure;
- every lifetime root and every function in each lifetime closure;
- grow target and every grow call target/site owner;
- all system allocators and finalizer/reset targets;
- callback target, setjmp target, longjmp target, and every finite callback
  candidate target; and
- the callback slot as a global-slot dependency.

Fresh success propagates this complete set before storing the memo entry. A
cache hit validates the stored fingerprints with `_dependency_memo_hit`,
replays the exact stored rows into the active outer collector, and returns the
certificate. An invalid entry is removed and recomputed. The in-progress or
proved-bottom sentinel remains bottom and supplies no positive proof.

The publication certificate adds its own caller/slice, call-target,
access/reference, incoming-owner, and import-binding dependencies on top of the
replayed totality dependencies.

## Persistence and rejection ledgers

The durable lifecycle query fields stay unchanged. The semantics value becomes
`object-tag-lifecycle-analysis-v6`, producing a different query digest and
preventing reuse of v5 finite or blocked files. Checkpoint schema v1 also stays
unchanged: it does not serialize the internal typed publication certificate,
returning bodies, imports, taint flows, backend bridges, or disjointness rows.
Durable assertions remain limited to the existing aggregate query/result plus
canonical function, global-slot, dynamic-field, and lifecycle-only
`absolute-reference` dependency rows and fingerprints. The in-memory lifecycle
v6 certificate binds:

- the compiler SHA-256 and unchanged analysis-limit envelope;
- active consumer binding, exact consumer caller, and slice through typed
  certificate identity plus function fingerprints; the query's minimum root is
  never substituted for the consumer caller;
- all returning closure functions and finite target functions;
- callback and publication slots;
- the context-bound totality/session/backend dependencies;
- exact incoming call owners and raw reconciliation; and
- the full query-independent lifecycle-only absolute-reference inventory and
  fingerprint, while closure-relative disjointness remains internal.

On a warm finite lifecycle-v6 checkpoint hit, durable dependency validation is
necessary but not sufficient: the file contains only aggregate values and
provenance, not the typed witnesses needed by recovery and audit. After
validating the stored dependency rows, `_ProducerCertificateSession.evaluate`
invokes the normal compute callback under the exact consumer-binding contexts
in a rehydration mode that consumes no query budget, does not increment
`completed_this_run`, and does not publish a replacement checkpoint. That
computation rebuilds the stage-appropriate certificate. The continuing
`_recover_indexed_table` entry loop rebuilds the tentative hypothesis from
current bytes; an accepted-candidate trial then installs the table, closes the
installed graph, finalizes normalization, and invokes the same rehydration
contract again for the definitive post-install query-bound dependency variant.
Only that final fresh aggregate result and exact dependency snapshot must equal
the stored post-install result and dependency tuple. A matching pre-install
variant cannot satisfy this check. `RawCfg` finalization then rebuilds the exact
provisional reconciliation-obligation union from the definitive certificates.
Otherwise the checkpoint is stale and the query recomputes normally or returns
bottom. Thus no finite warm hit can bypass typed-witness reconstruction.

External residue acceptance is not checkpoint evidence. A hostile warm-hit
case with valid durable dependencies but changed, missing, extra, or stale
external reconciliation must rebuild the current obligation union and remain
unpublishable. Final publication still requires the current Ghidra/residue
reconciliation and its obligation-set-bound crosscheck digest.

`movzx-producer-analysis-v27` remains byte-for-byte the producer semantic
identity. Existing v27 certificates continue to validate when their own
dependencies are unchanged.

The relocated-rejection ledger contract already includes lifecycle semantics.
Consequently a ledger created under v5 must miss under v6, rerun the rejected
hypothesis, and write a v6-bound ledger. A v27 producer field remains present
and unchanged. Malformed or manually relabeled v5 records remain invalid rather
than being migrated in place.

## Failure behavior

Every ambiguity returns bottom and preserves the unresolved dispatch. This
includes an open caller domain, caller outside the certified backend closure,
same-root or stale-alias republish, unresolved target, returning failure
callback, overlapping callback-slot write, in-closure slot reference, ambiguous
outside-residue reference, address materialization, root/child/slot-address
actual, tainted dereference, unknown or mismatched import, missing reference
reconciliation, ownership growth into a returning range, failed external
residue reconciliation, split-backend union, dependency limit, or stale memo or
checkpoint entry that cannot be revalidated/recomputed.

No partially proved publication is recorded as safe. A positive provenance
string identifies the publication, observation, slice digest, returning closure
digest, exact backend root/session, and opaque-copy escapes without claiming
that those values do not escape.

## Expected retail result

The focused static retail recovery should admit the 29 calls whose only
remaining blocker is the `0x435628` publication, retaining the existing table
integrity checks and lifecycle bound. The read-only retail verifier also checks
the 39-body returning closure, 56-body default callback closure, five exact
DLL/name/IAT import identities, the complete `0x587130` reference inventory,
and its six externally reconciled provisional executable sites. It requires
exactly one audit row, exactly 19 unique full reference rows, validates every
span/byte/relocation/source-evidence field, recomputes the canonical reference
inventory SHA-256, and checks each of the six provisional rows against its
exact containing interval/hash and the reconciliation digest that accepted it.
The thirtieth call at `0x4b1f95` is
checked separately and must remain unresolved until its independent ESP-slot
receiver/argument binding is proved. It must not acquire publication
noninterference provenance by accident. The retail verifier checks both the
absence of a lifecycle jump-table admission and the absence of any
`return-path-publication-noninterference` certificate/provenance row bound to
`0x4b1f95`, checking both explicit integer fields and normalized hexadecimal
strings in nested provenance.
