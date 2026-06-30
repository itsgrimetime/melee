# Raw Index And Data Table Transform Design

## Goal

Make `raw_index_struct_field_shape` and `data_table_indirection_shape` executable for narrow, locally proven cases without adding a parallel layout or alias-analysis system.

## Scope

This feature adds two concrete mutators:

- `rewrite_raw_index_struct_field`
- `rewrite_data_table_indirection`

Both mutators use exact validated spans and only replace text when the payload still matches the current source. They do not attempt broad C parsing, cross-TU inference, archive introspection, or alias analysis.

## Raw Indexed Struct Field Proof

The raw-index mutator covers simple load and store lines where the base is a typed pointer parameter and the indexed byte offset can be proven from a source-local struct layout:

```c
value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);
*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10) = value;
```

When `entries` is an `Entry*`, `Entry` is a source-local typedef struct with an explicit field at `0x10`, and the cast type exactly matches that field type, probes rewrite to:

```c
value = entries[i].field;
entries[i].field = value;
```

The struct proof extends the existing `raw_pointer_offset_struct_field_shape` helper style. The typedef struct must be visible before the target function, and pointer parameters must make the base type visible at the rewritten use. It supports explicit scalar/pointer fields and explicit `u8 pad[N]` padding. It rejects unions, bitfields, packed or implicitly aligned layouts, arrays except padding, multi-declarator fields, unknown field sizes, duplicate `(type, offset)` fields, and unknown struct size. Index scale must be `sizeof(StructType)` or a literal equal to the recovered simple struct size. Index expressions are restricted to simple identifiers or integer literals.

## Data Table Indirection Proof

The data-table mutator covers source-local outer table declarations where a direct table symbol appears exactly once in an initializer:

```c
static s32* const sOuterTable[] = { table_a, table_b, table_c };
value = table_b[idx];
```

The generated probe rewrites read expressions to:

```c
value = sOuterTable[1][idx];
```

This first slice only rewrites reads, not writes. It requires a top-level immutable pointer-array declaration before the target function, such as `static s32* const sOuterTable[] = { ... };`, with simple identifier elements, a unique target element, and a direct read expression `symbol[index]` in the target function body. It also requires a visible top-level declaration for the direct symbol before the target function, such as `extern s32 table_b[];` or `static s32 table_b[];`.

The full source is scanned for reassignments or address-takes of both the outer table symbol and the direct element symbol. Any write or address-take outside the table initializer rejects the proof, because the initializer only proves current identity when both symbols are immutable for the search unit. The analyzer also rejects duplicate elements, local shadowing of the table or direct symbol, preprocessor-hidden declarations, comments/strings, writes through the rewritten expression, complex index expressions, and ambiguous element types.

## Integration

`raw_index_struct_field_shape` and `data_table_indirection_shape` are no longer record-only. Their family metadata advertises the new mutator keys, generated probe forms, and high semantic risk. The generic fallback cluster includes both families now that they can emit guarded probes.

`rewrite_raw_index_struct_field` and `rewrite_data_table_indirection` are implemented as exact span replacements via the existing directed mutator dispatch. Provenance includes family id, mutator key, probe id, access kind, base/table symbols, struct/table proof source, field offset/type, index expression, and original/replacement text.

Two anchor generators plug into `_iter_full_source_anchors()`:

- `_iter_raw_index_struct_field_anchors(source_text, span)`,
- `_iter_data_table_indirection_anchors(source_text, span)`.

The generators yield anchors whose mutator keys map through `_FAMILY_IDS_BY_MUTATOR`, so `generate_transform_probes()` materializes them through the same path as the existing raw-pointer offset and global-float probes.

## Safety Rules

The implementation abstains rather than guessing. It rejects any source body or declaration region that needs:

- implicit C alignment decisions,
- macro expansion,
- cross-translation-unit symbols,
- alias reasoning,
- side-effect reasoning in writes,
- type compatibility beyond exact normalized spelling,
- bitfield width/sign proof,
- table layout inferred from runtime data or archives.
- mutable table or element pointer identity.

This leaves some legitimate real-world cases manual, while keeping emitted probes constrained enough for directed search agents to try automatically.

## Tests

Regression coverage must prove:

- both families are no longer record-only and expose concrete mutator keys,
- raw-index load and store fixtures generate exact typed field access probes,
- raw-index unsafe fixtures reject unknown struct layouts, declarations after the target, implicit alignment, mismatched cast type, wrong scale, non-pointer bases, complex indexes, preprocessor bodies, bitfields, and duplicate field proofs,
- data-table read fixtures generate exact outer-table probes,
- data-table unsafe fixtures reject duplicate table entries, mutable/non-const pointer tables, missing direct-symbol declarations, declarations after the target, writes or address-takes of the table or element symbol, complex indexes, local shadows, non-top-level declarations, and preprocessor-hidden tables,
- both mutators reject stale or mismatched spans,
- command-level `plan-transforms --write-probes --json` materializes candidates for both families through the generic cluster,
- catalog docs and source catalog counts reflect the two new executable forms.
