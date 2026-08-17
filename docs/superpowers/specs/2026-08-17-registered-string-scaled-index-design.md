# Registered-string scaled-index provenance design

## Context

The authoritative issue #1240 call-slot replay now crosses the reviewed
unobserved-callee alias boundary and stops at owned call
`0x408cbc -> 0x403c50`. The call is recognized as the existing bounded scalar
formatter, but its `%s` argument has no registered-string length domain.

The registered-string reader computes a record index in two register families:
the loop counter remains in one family, while an address temporary receives
`counter + counter * scale` and is then used by the table load. The current
proof incorrectly requires the temporary and counter to use the same register
family. This rejects the retail shape even though all table, writer, key,
payload, and immutable-string facts are otherwise exact.

## Design

Keep `_registered_string_record_length_domain_before` address-independent and
split the two proven roles:

1. Derive `scaled_index_family` from the table load's index register.
2. Require its unique reaching definition to be a full-width `LEA` whose
   destination is exactly `scaled_index_family`.
3. Require the LEA base and index to be valid registers from one identical
   `counter_family`; they need not equal `scaled_index_family`.
4. Compute the record stride from the LEA scale and table-load scale exactly as
   today.
5. Feed `counter_family`, rather than the address temporary, into the existing
   bounded postincrement-counter proof.
6. Preserve all existing exact writer/reader field inventories, zero-initial
   table checks, finite key domain, relocation/reference checks, immutable
   string checks, and caps.

No address, byte, function-name, hash, or compiler-marker exception is added.
No TOP value, mixed-family LEA, partial register, unknown definition, or work
limit is admitted.

## Alternatives rejected

- A retail-address or exact-byte exception would not establish the semantic
  relationship and would violate the fail-closed proof contract.
- Extending the general affine-value interpreter would prove more than this
  boundary needs and would enlarge currentness and adversarial-review scope.
- Treating any scaled table load as the counter would retain the present false
  rejection and would still conflate the two roles.

## Test contract

Extend the existing registered-string record fixture rather than creating a
retail-shaped special case:

- Preserve the existing same-register positive and add a positive that uses a
  distinct full-width temporary for `counter + counter * 2`, then loads the
  record pointer through that temporary.
- A one-fact hostile changes one LEA input to another register family while
  retaining the same destination, table load, CFG, and surrounding writer and
  reader facts. It must return `None`.
- Existing same-family, detached-key, partial-write, mutable-name, wrong-field,
  wrong-source, wrong-stride, and zero-key cases retain their current outcomes.
- The focused RED must fail only for the new valid distinct-family positive;
  the original same-register positive and mixed-source hostile must already
  have their expected outcomes before production changes.

After GREEN, run the focused registered-string/immutable-format matrix, the
adjacent private-stack scalar-format selection, scoped static checks, current
retail mini-query, independent review, the full x86 module, and only then the
restart-safe authoritative call-slot replay. Publication roots remain gated on
an exact positive call-slot row.

## Currentness and failure behavior

The helper remains a pure query over current recovery facts and introduces no
cache or durable authority. Missing or non-unique definitions, partial-width
operands, mixed LEA input families, unsupported scales, incomplete counter
domains, mutable table/string evidence, or any downstream mismatch returns
`None`. Existing analysis limits remain unchanged.
