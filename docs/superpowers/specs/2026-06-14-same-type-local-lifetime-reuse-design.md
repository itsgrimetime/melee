# Same-Type Local Lifetime Reuse Transform-Corpus Design

## Goal

Make `same_type_local_lifetime_reuse` executable for narrow, source-local local-variable reuse experiments. Matching agents should be able to request the family from `plan-transforms` and receive guarded candidate source files instead of record-only metadata.

## Scope

The first executable form is intentionally conservative: within one target function body, find two top-level simple local declarations with the same normalized type where the earlier local's last use is before the later local's first use. Emit a probe that deletes the later declaration and rewrites later-local identifier uses to the earlier local. This covers the PR #2674 `it_802BCB88` pattern where `cur` is reused for the later `prev` phase while keeping the inline helper call shape intact.

Supported declarations are scalar locals already accepted by existing scalar helpers and simple pointer locals such as `ItemLink* cur;`. The pass does not move declarations, merge nested scopes, rewrite initializers, infer dominance through arbitrary C, or edit headers. If local spans are not straightforward to prove, it rejects the shape.

## Safety Rules

The source pass only considers declarations at depth zero inside the requested function body. Depth must be computed from comment/literal-blanked text so braces inside strings or comments cannot make nested declarations look top-level. It rejects preprocessor regions, label/case/default-sensitive bodies, loop bodies for v1, nested declarations of either candidate name, declaration initializers, declaration-line comments that would be deleted, volatile-qualified declarations or volatile-looking body text, address-taken candidates including parenthesized forms such as `&((name))`, and any same-name mention before the local declaration.

Identifier mentions are found after blanking comments and literals, and field names such as `obj.prev` or `obj->prev` are not treated as variable uses or rewrite sites. Positive fixtures must prove string/comment text remains unchanged when a valid candidate is otherwise emitted. A candidate is emitted only when:

- both locals have the same normalized scalar or pointer type,
- the earlier local has at least one post-declaration use,
- the later local has at least one post-declaration use,
- every earlier-local use occurs before the first later-local use,
- the first later-local event is a simple assignment to that local,
- every later-local use to rewrite occurs after its declaration, and
- neither local is address-taken.

This proves a simple non-overlap boundary without trying to solve full C dataflow. The generated candidate is built from exact spans in the target body, then the mutator validates the cited target-body span before replacing it. Stale spans must return `None`; the mutator must not fall back to replacing the same text elsewhere in the file.

## Integration

`same_type_local_lifetime_reuse` moves from record-only metadata to one concrete mutator key:

- `reuse_same_type_local_lifetime`

The anchor generator lives in `transform_corpus.py` because it needs full target-function text and source spans, similar to the other full-source transform-corpus generators. The mutator in `mutators.py` replaces an exact scoped body segment with a precomputed rewritten segment after validating the cited span. Common `TransformProbe` provenance still supplies `family_id`, `mutator_key`, `probe_id`, and source span. The family-specific payload records the reused/original local names, normalized type, declaration spans, first/last use offsets, replacement count, and the removed declaration line.

The human and machine source-transform catalogs must stop describing this family as record-only and include the new concrete form in the directed mutator count.

## Tests

Regression tests must prove:

- metadata shows `same_type_local_lifetime_reuse` has `reuse_same_type_local_lifetime` and is no longer record-only,
- the `it_802BCB88`-style pointer fixture deletes `prev`, rewrites the later phase to `cur`, and preserves helper-call shape,
- a scalar same-type fixture emits a candidate,
- probe provenance includes names, type, declaration spans, replacement spans, use offsets, replacement count, family id, mutator key, and stable probe id,
- direct `apply_mutator` rewrites only the validated scoped segment and rejects stale spans,
- overlapping lifetimes are rejected,
- address-taken candidates are rejected,
- nested declarations or non-top-level candidate declarations are rejected,
- preprocessor, label, `case`, and `default` regions are rejected,
- mismatched types and initializer declarations are rejected, and
- comments/literals are not rewritten in an otherwise valid candidate,
- member names are not counted as local variable uses or rewritten, and
- braces in comments/literals do not affect declaration-depth classification.

Command-level smoke should run `debug search plan-transforms --write-probes --json` against a temporary fixture, verify the JSON includes a `same_type_local_lifetime_reuse` probe, and verify a written candidate file contains the `cur` reuse shape.
