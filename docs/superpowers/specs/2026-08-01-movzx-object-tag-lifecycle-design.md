# MOVZX Object-Tag Lifecycle Design

## Goal

Close the retail offset-zero object-tag dispatch family only when the complete
object lifecycle proves a finite byte domain independently of the dispatch
table's relocation run.

## Architecture

Keep `movzx-producer-analysis-v25` and its certificates unchanged. Add a
separate lifecycle query and durable certificate used only as a fallback after
the pointwise producer proof cannot narrow a byte load. The query groups
structurally equivalent consumers by indexed-table shape and object field, but
each consumer must independently prove that the table index and argument zero
come from the same receiver.

The lifecycle analysis scans every owned write overlapping the requested object
byte. It accepts only exact immediate-byte initialization on a fresh allocation,
finite forwarding through closed callers, nonrecursive field associations, and
recursive identity edges whose terminating origins are all closed. The least
fixed point is intentionally identity-only: revisiting the same recursive
formal at a different field path returns bottom. It computes the least finite
domain from the remaining lifecycle roots. Unknown, overlapping,
uninitialized, escaping, non-private local-stack aliases, nonidentity recursive
associations, or open-caller paths return bottom.

The resulting `movzx-lifecycle-domain` guard is passed to the existing indexed
table recovery. Existing type-3 relocation and executable-target requirements
remain authoritative for every admitted slot. Relocations never create or
extend the lifecycle domain.

## Persistence and invalidation

Lifecycle certificates use their own schema and semantics under the existing
checkpoint root. Their dependencies include every participating function and
the dynamic field being proved, so caller growth or any overlapping field write
invalidates the certificate. Existing v25 producer files retain their query,
schema, digest, and discovery behavior.

## Tests

A real synthetic PE supplies two cross-function consumers, variable-size fresh
allocations, and endpoint tags 0 and 74. Hostile mutations cover open callers,
unknown and out-of-domain writers, receiver/argument mismatch, missing
relocations, and non-executable entries. Tests assert observable CFG results,
not analyzer internals or address allowlists.
