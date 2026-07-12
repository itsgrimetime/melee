# Issue #1238: Reviewed Namespace Sidecar

## Context

The v5 automatic allocator-namespace solver is sound and fail-closed. It proves
a complete pairwise mapping from early pre-allocation IR only when every CFG
block, instruction position, operand occurrence, register kind, and reviewed
anchor has a unique round-trip correspondence. It correctly rejects the frozen
`mnDiagram_DrawFighterHeaders` left/right parents because the compiler moves
instructions across a branch/join boundary and changes several relocation
families.

The original issue explicitly asks for a provenance-bound reviewed
cross-parent role map when automatic semantic proof is ambiguous. The existing
v2 color target binds only the absolute force-physical roles 64 and 78. It
cannot authorize the complete allocator namespace needed for secondary color
profile comparison.

## Goal

Add a run-bound review artifact that explicitly attests complete allocator-role
bijections for only the exact parent/candidate artifacts the automatic solver
cannot prove. Automatic proof remains authoritative wherever it succeeds.

## Approaches

### Separate reviewed-namespace sidecar — selected

Keep the reusable v2 color target focused on absolute target roles. A separate
sidecar binds full maps to the exact delta lattice, compiler context, sources,
pcdumps, parser epoch, and discovery request. This cleanly separates an
objective from a run-specific review decision.

### Embed maps in color-target v3

This offers one input file but couples a reusable target to one parent pair and
candidate lattice, creates a large target, and makes candidate discovery
circular.

### Global attestation registry

Content-addressed attestations could be reusable across runs, but lookup,
trust, lifecycle, and conflict semantics are beyond this issue.

## Schemas

Discovery writes `delta-minimize-namespace-review-request.v1`. A sealed review
uses `delta-minimize-reviewed-namespaces.v1`.

Both bind:

- function and register class;
- role-namespace schema and parser schema hash;
- v2 target content hash;
- canonical delta-manifest hash;
- left and right source hashes;
- cflags hash, compiler fingerprint, expected-object hash, and inspector
  version;
- canonical artifact identity and its source/pcdump hashes;
- every captured parent/candidate artifact id, mask, source hash, pcdump hash,
  automatic-resolution state, and diagnostic;
- a canonical request SHA-256.

The sealed review contains bindings only for unresolved content identities.
Each binding records its artifact identity and a fully expanded
`canonical_to_artifact` mapping. For GPR class 0 in the retained run the exact
key/value domain is `0..109`: ABI roles `0..31` must map identically and true
virtual roles `32..109` must form a complete bijection. No `identity` shorthand
is accepted in the sealed authority.

## Workflow

Add `--namespace-review PATH` to `debug search delta-minimize` and add:

```text
melee-agent debug search delta-namespace-review seal \
  --request REQUEST.yaml \
  --accept-identity parent:right \
  --accept-identity candidate:mask-100 \
  --map candidate:mask-N=map.yaml \
  --out reviewed.yaml
```

The first run without a sufficient review must capture both parents, extract
and materialize the exact lattice, capture raw evidence for all candidates,
and attempt namespace resolution before objective publication. It writes a
deterministic request and an incomplete result instead of stopping at the
first parent ambiguity.

The seal command is the explicit review action. `--accept-identity` expands the
complete domain into explicit pairs; `--map` accepts a full nonidentity map.
It validates the request and selected artifact ids before writing atomically.

The rerun with `--namespace-review` reuses compatible raw evidence, validates
the review against the current request/context, resolves namespaces, then
continues ordinary objective profiling and exact enumeration.

## Resolution order

For each artifact:

1. Inherit a resolved map only from an exact `(source_sha256, pcdump_sha256)`
   pair.
2. Use the strict automatic v5 pairwise solver.
3. Use an exact reviewed binding only when the request recorded that content
   identity unresolved under the same namespace/parser epoch.
4. Otherwise remain incomplete.

Automatic proof cannot be overridden. A reviewed entry for an automatically
resolved artifact is invalid. Pcdump-only equality is insufficient.

The review authorizes namespace identity only. It never supplies physical
assignments, interference, coalescing, simplify/select order, ObjObject order,
or stack-home truth.

## Validation and safety

- Use unique-key YAML and exact field sets.
- Reject symlinked review paths and malformed or non-lowercase SHA-256 values.
- Recompute source/pcdump hashes from captured evidence.
- Validate artifact ids, kinds, side/candidate mask, function/class, target,
  delta, compiler, cflags, expected object, inspector, parser, and request hash.
- Derive the role domain from coherent class evidence; reject bool-as-int,
  missing/extra keys, out-of-domain values, duplicate values, nonidentity ABI,
  and incomplete virtual bijections.
- Require parent maps to agree with v2 reviewed anchors 64 and 78.
- Reject missing, extra, redundant, conflicting, or now-automatically-provable
  reviewed entries.
- Duplicate exact content pairs must resolve to one identical map.
- Invalidate current publications before discovery/rerun while preserving
  compatible content-addressed raw evidence caches.

## Epochs and persistence

Add a namespace-resolution epoch containing the v5 namespace schema, reviewed
sidecar schema, and review digest. Bind it to objective inputs, objective
manifest provenance, profile/publication context, and cache keys.

Bump the objective-input schema and objective-manifest schema. The raw parser
epoch need not change because the sidecar changes resolution, not capture
parsing; any later automatic solver change requires rediscovery.

## Retained acceptance

The retained run automatically proves masks `000`, `001`, `010`, and `011`.
The minimal sealed review contains four explicit identity maps:

- `parent:right`;
- `candidate:mask-100`;
- `candidate:mask-101`;
- `candidate:mask-110`.

`mask-111` inherits `parent:right` only because both source and pcdump hashes
match. Final acceptance requires 8 legal, 8 viable, 8 complete candidates,
`exact_four_axis: true`, no blockers, Pareto masks `000/001/010/011`, and
`best_next=mask-000`.

## Testing

- Strict request/review schema, map-domain, hash, context, anchor, duplicate,
  and drift rejection tests.
- Resolver precedence: exact inheritance, automatic proof, reviewed fallback,
  incomplete; automatic results cannot be overridden.
- First-run integration writes a complete deterministic request despite parent
  ambiguity and captures all candidate evidence.
- Seal integration expands identity/nonidentity maps and rejects missing,
  redundant, or extra approvals.
- Reviewed rerun reuses raw caches and publishes only when every viable
  namespace is resolved.
- Retained acceptance uses the four explicit maps above and preserves exact
  endpoint hashes and frontier.
