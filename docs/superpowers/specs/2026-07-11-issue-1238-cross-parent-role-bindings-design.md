# Issue #1238: Proven Cross-Parent Role Bindings

## Context

The two-frontier delta minimizer derives the same absolute GPR target from both
retained `mnDiagram_DrawFighterHeaders` parents: `IG64 -> r30` and
`IG78 -> r29`. The generic role matcher correctly refuses to reanchor either
role into the other parent because each has two zero-cost semantic matches.
`delta-minimize-color-target.v1` can bind the force-physical target to one
baseline dump, but it cannot record a reviewed assertion that selects one of
those otherwise indistinguishable matches in both retained parents.

The relevant real artifacts prove the ambiguity:

- left IG 64 matches right IGs 54 and 64 at cost zero;
- left IG 78 matches right IGs 61 and 78 at cost zero;
- the reviewed intended mapping is identity for both roles;
- left source/dump hashes are
  `0f38bf2740123c3bbf6b9c18ad10123cc0db3f6e14bd5041057d49921eaec7e2`
  and `db41d64051334cace6e38b2db91ade6d6addfff0a4ab06b689b5cc1384578333`;
- right source/dump hashes are
  `e7f3a66ab56c14b8841591ade19425c4cb45df614795ef15e4d9fa983967af96`
  and `433e4954aa3b4402dedb61ef9830ac6aa03a393b1147217654f62e0350196598`.

Assigned registers and live ranges distinguish the retained instances, but
they remain allocator state rather than general semantic identity. The generic
role matcher must not start using them as automatic tie-breakers.

## Goal

Allow a reviewed, provenance-bound cross-parent role mapping to resolve the
retained-parent ambiguity without weakening the generic role matcher, while
keeping every hybrid candidate fail-closed unless its role namespace is proven.

## Non-goals

- Do not change generic `role_cost()` or make raw IG equality identity evidence.
- Do not accept unbound CLI-only role maps.
- Do not require a human-authored map for every generated hybrid.
- Do not publish an exact frontier when any viable hybrid lacks a proven map.
- Do not change opcode, ObjObject, or stack-home objective semantics.

## Approaches considered

### 1. Versioned parent-role bindings and namespace propagation

Add a v2 target schema whose reviewed maps are bound to both retained source
and pcdump hashes. Use those maps for the two parents. A hybrid may inherit a
parent map only when a versioned structural namespace witness is exactly equal;
otherwise it must pass ordinary semantic reanchoring.

This is the selected approach. It scopes the assertion to immutable evidence,
survives resume and cache validation, and preserves fail-closed behavior.

### 2. Enrich the generic role descriptor

Add normalized PCode positions or source-enclosing anchors to every role and
let the generic matcher distinguish the repeated blocks automatically. This
could eventually improve all reanchor consumers, but it is much broader than
the blocker and could change established matching semantics.

### 3. Require a reviewed map for every hybrid

Compile all hybrids, stop, and require a map for each pcdump before scoring.
This is explicit but operationally defeats autonomous exact enumeration and is
not ergonomic for a bounded delta search.

## Target schema

Continue accepting `delta-minimize-color-target.v1` exactly as today. Add:

```yaml
schema_version: delta-minimize-color-target.v2
function: mnDiagram_DrawFighterHeaders
class_id: 0
baseline_side: left
baseline_dump: /absolute/path/to/left.pcdump
force_phys:
  64: 30
  78: 29
coalesce_preservation: false
parent_role_bindings:
  left:
    source_sha256: 0f38bf2740123c3bbf6b9c18ad10123cc0db3f6e14bd5041057d49921eaec7e2
    pcdump_sha256: db41d64051334cace6e38b2db91ade6d6addfff0a4ab06b689b5cc1384578333
    canonical_to_parent:
      64: 64
      78: 78
  right:
    source_sha256: e7f3a66ab56c14b8841591ade19425c4cb45df614795ef15e4d9fa983967af96
    pcdump_sha256: 433e4954aa3b4402dedb61ef9830ac6aa03a393b1147217654f62e0350196598
    canonical_to_parent:
      64: 64
      78: 78
```

The map direction is canonical baseline IG to raw parent IG. The v2 loader
requires exact top-level and nested fields, both `left` and `right`, lowercase
64-character SHA-256 strings, maps whose keys exactly equal `force_phys`,
non-negative integer IGs, and injective destinations. The baseline-side map
must be identity. `baseline_dump` content must match the baseline-side pcdump
hash.

During objective inference, each binding must match the actual parent source
and pcdump bytes. Every canonical and mapped IG must exist in the declared
register class. The mapped descriptor must be a viable minimum-cost semantic
candidate for its canonical baseline descriptor; the explicit assertion may
choose among tied minima but cannot select an unrelated role.

## Objective and candidate data flow

The objective target remains expressed in the baseline canonical role
namespace. V2 provenance records:

- the v2 schema identifier;
- the baseline side and dump hash;
- both source and pcdump hashes;
- both reviewed canonical-to-parent maps;
- the structural namespace witness schema version.

Parent color profiles use the reviewed bindings directly for required target
roles. The existing full-profile semantic map is retained for other roles and
is overlaid only when the reviewed mapping is one-to-one and conflict-free.

Candidate evaluation recognizes the two retained parent pcdump hashes and uses
their reviewed maps directly. A non-parent hybrid may reuse a parent mapping
only when its structural namespace witness exactly matches that parent. The
witness includes:

- register class and virtual count;
- raw-IG-indexed normalized semantic def/use identity;
- decision and simplify traversal identity;
- coalesce projection and forced overrides.

It excludes assigned physical registers, interference edges, spills, and live
ranges because those are objective state. If neither parent witness matches,
candidate evaluation falls back to ordinary descriptor reanchoring. Ambiguous
or incomplete mapping leaves the viable candidate incomplete, which prevents
exact Pareto publication.

## Cache and publication safety

The objective-input envelope already binds target-file content. V2 also binds
every external artifact used by the reviewed mapping. The implementation bumps
the objective-manifest and candidate-evidence/parser semantic versions so
evidence created before the new meaning cannot be reused.

The serialized objective manifest must retain and validate all binding and
witness provenance. Any tampering, hash mismatch, unsupported witness version,
partial map, duplicate destination, wrong side, missing IG, or changed source
causes a specific fail-closed target or corrupt-manifest error. No fallback may
silently reinterpret a malformed v2 target as v1.

## User-facing behavior

The CLI surface remains `--target PATH`. Help and documentation describe v1 as
the automatic semantic-reanchor format and v2 as the reviewed cross-parent
binding format. Ambiguity without valid v2 evidence continues to report
`ambiguous-color-target` and direct the operator to a versioned target.

## Testing and acceptance

Tests cover:

- strict v2 parsing, baseline binding, total/injective maps, hash checks, class
  and descriptor compatibility, and v1 compatibility;
- the duplicated-role reproduction where v1 remains ambiguous and v2 resolves
  both parents;
- parent endpoint mapping, exact namespace inheritance, and rejection when
  def/use identity, traversal, coalesce projection, or artifact hashes change;
- objective round-trip, tamper rejection, and cache invalidation when bindings
  or witness versions change;
- an integration fixture with two repeated indistinguishable role pairs and a
  complete four-axis frontier under v2;
- incomplete publication when any viable hybrid cannot prove its mapping.

Real-case acceptance reruns Section 15.3 with the retained wrapper and direct
parents, the reviewed identity bindings for IGs 64 and 78, and a candidate
budget of 64. It must produce status `matched`, `joint-zero`, or `frontier`,
with complete evidence for every viable mask and no identity guess.
