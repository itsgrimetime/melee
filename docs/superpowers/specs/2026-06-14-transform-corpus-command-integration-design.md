# Transform Corpus Command Integration Design

## Context

Issues #683-#686 have one root cause: guarded transform-corpus probes can be
planned and written by `debug search plan-transforms`, but the commands agents
use while matching do not consume those probes. The newly concrete mined
families from commit `6cda20c4b` are therefore discoverable only if an agent
already knows to run the planning command manually.

Issue #682 was investigated separately. The reported `codex-rescue` hang is
implemented by the external OpenAI Codex Claude plugin, not by this repository
or the editable `melee-agent` install, so it is outside this spec.

Human review is intentionally skipped for this automation run per the
issue-resolver instructions. Independent Codex subagent review replaces the
human approval gate.

## Clarified Requirements

The feature must make transform-corpus probes available through existing
matching surfaces without changing default scoring behavior for broad scorer
commands.

`debug search directed` and `debug search run --directed-force-phys` should
use the corpus generator as a bounded source-shape fallback after
diagnosis-resolved source ideas. The fallback must keep attribution honest:
diagnosis-driven candidates remain attributed; transform-corpus candidates are
tagged as source-shape/proof-vector-planned probes and carry family metadata.

`debug mutate lifetime-layout`, `debug coalesce-search`,
`debug select-order-search`, and `debug mutate frame-transform-search` should
gain opt-in transform-corpus probe generation. The explicit
`--include-transform-corpus` flag opts in, and passing `--transform-family`
also opts in because a family filter without probe inclusion would be
surprising. Current defaults must remain unchanged when neither option is used.

Documentation, catalog metadata, help text, and capability search should tell
matching agents which command to run for planning, live directed search,
pressure/coalescing/select-order scoring, and frame-transform scoring.

## Alternatives Considered

### 1. Inline `generate_transform_probes` separately in every command

This is the quickest patch, but it repeats family filtering, label generation,
and provenance mapping across five command bodies. The duplication would make
it easy for one command to lose `family_id` or produce different candidate
labels, and it would make future transform families harder to wire correctly.

### 2. Replace existing lifetime/frame generators with transform-corpus probes

This would make transform-corpus probes visible everywhere, but it changes the
meaning of mature commands that already have objective-specific probes. It
would add noise to workflows that need targeted pressure or frame candidates,
and it risks changing existing command behavior without an explicit request.

### 3. Add a shared adapter and opt-in command plumbing

This is the chosen design. A small adapter converts `TransformProbe` into the
existing `LifetimeLayoutProbe` shape used by source-scoring commands. Directed
search gets a separate proposal iterator that uses `TransformProbe` metadata
directly while still applying the selected mutator through the existing
`DirectedSource` path. This keeps the integration reusable, testable, and
consistent without replacing specialized generators.

## Design

### Shared transform-probe adapter

Add `tools/melee-agent/src/search/directed/transform_probe_adapter.py` near the
directed-search implementation. It will:

- normalize and validate repeated `--transform-family` values against
  `DEFAULT_TRANSFORM_FAMILIES`;
- allow valid record-only families as filters even when they produce no probes;
- filter `TransformProbe` objects by requested family values;
- cap the total returned probe count, because `generate_transform_probes` only
  caps per family;
- de-duplicate identical `candidate_text` so scoring loops do not compile the
  same source repeatedly under different family aliases;
- convert each probe to `LifetimeLayoutProbe` with stable labels of the form
  `transform-corpus-<family_id>-<ordinal>`;
- set `operator` to `transform-corpus:<family_id>`;
- preserve `family_id`, `family_label`, `mutator_key`, `probe_id`, source
  region, semantic risk, expected compiler effect, generated form, span,
  payload, and target assignments in `provenance`;
- provide a compact `force_phys` parser for transform-corpus command flags so
  debug CLI code does not import parsing helpers from the search CLI command
  module.

The adapter does not compile, score, or decide whether a probe is useful. It
only bridges a proven source rewrite into command-specific scoring pipelines.
`LifetimeLayoutProbe.to_dict()` should copy `probe_id`, `family_id`, and
`mutator_key` to the top level when the provenance kind is `transform-corpus`,
while keeping the full metadata under `provenance`.

### Directed search integration

Replace the old directed source-shape allow-list fallback with a
transform-corpus proposal path. Diagnosis-resolved `source_idea` anchors stay
first. If no diagnosis anchor applies, `_source_shape_proposal` should call
`generate_transform_probes(source_text, function, unit, force_phys, ...)` and
return one untried probe at a time.

The tried key is a file/provenance-safe key, e.g.
`transform-corpus:<family_id>:<ordinal>`, so repeated anchors do not loop and
the current fallback mutator suffix stripping never treats the corpus key as a
plain mutator. The existing `DirectedSource` no-loop guard continues to own
retry protection. The apply function maps this key back to `candidate_text`
directly for corpus probes; normal mutator keys still use `apply_mutator`.

Producer metadata must include `source_shape`, `transform_corpus`,
`proof_vector_planned`, and the full probe provenance. It must not use
`non_actionable`. These probes are concrete guarded source edits selected from
the current source text and planned under the proof vector, but they are not
diagnosis-specific source ideas.

Dry directed tests should exercise this proposal layer without running MWCC.

### Scoring command integration

Add opt-in flags to the four scoring surfaces:

- `--include-transform-corpus/--no-include-transform-corpus`;
- `--transform-family FAMILY`, repeatable and comma-splittable;
- `--transform-force-phys IG:PHYS`, repeatable and comma-splittable, with
  `--directed-force-phys` accepted as an alias where consistent with existing
  search commands.

Without `--include-transform-corpus` or `--transform-family`, current probe
lists must be unchanged. With transform-corpus enabled, commands append corpus
probes after their existing objective-specific probes until `--max-probes` is
reached. This preserves specialized command intent while exposing corpus
candidates when requested.

If no force-phys vector is supplied, the command should still work by passing
an empty proof vector to `generate_transform_probes`. The current corpus plan
has a generic fallback cluster, and the generator remains proof-gated at the
family/mutator level. Supplying `--transform-force-phys` makes provenance more
specific but is not required to list syntactically guarded probes.

For `frame-transform-search`, keep frame-directed probes first and lifetime
fallback probes second. Corpus probes are appended after those probes by
default, so they cannot crowd out PAD_STACK or semantic frame levers under a
tight `--max-probes`. When transform-corpus is enabled without an explicit
family filter, use a small frame-relevant default list:
`assignment_expression_temp_seed`, `string_literal_data_blob_field_shape`,
`raw_pointer_offset_struct_field_shape`, `comma_operator_noop_expression_shape`,
`numeric_cast_shape`, `void_to_value_return_shape`,
`global_pointer_alias_shape`, and `empty_do_while_barrier`. Explicit
`--transform-family` values override that frame default and can request any
valid corpus family.

JSON output already includes `probes`; converted probes should expose top-level
`probe_id`, `family_id`, and `mutator_key` plus full provenance. Variant
records that already attach `probe` payloads should therefore include transform
metadata automatically. Text output should show the generated source directory
and probe labels/operators in the existing format. `select-order-search
--beam-depth` stays on existing lifetime probes for this pass; adding corpus
probes to every beam expansion would change search-frontier semantics.

### Documentation and discoverability

Update `docs/source-transform-catalog.md` and
`tools/melee-agent/src/mwcc_debug/source_transform_catalog.py` to distinguish:

- planning and probe writing via `debug search plan-transforms`;
- live directed search via `debug search directed` and `debug search run
  --directed-force-phys`;
- opt-in pressure/coalescing/select-order scoring;
- opt-in frame-transform scoring.

Help strings for the new flags should include `transform-corpus` and
`source-shape` terms so `melee-agent capabilities search "transform corpus
source-shape probes"` returns the new surfaces. Add capability regression tests
for transform-corpus queries.

## Error Handling

Invalid transform-family filters should fail before scoring starts and report
the unknown family id plus a short hint to inspect `debug search
plan-transforms`. Valid but currently record-only families are not errors; they
may simply produce zero probes.

Invalid `--transform-force-phys` values should use the existing
directed-force-phys parser where possible and exit with code 2.

If transform-corpus generation returns no probes under the requested filters,
commands should continue with existing probes. If no existing probes or
candidates exist either, they should use the command's current no-probe error.

Generated source candidates continue to use existing prevalidation and compile
error reporting. The adapter must not hide malformed-source diagnostics.

## Tests

Add tests before production changes where practical:

- directed proposal tests proving all ten newly concrete mined families can be
  emitted through the directed proposal helper with stable transform-corpus
  tried keys and metadata, and that repeated `next_batch` calls do not retry
  the same probe;
- regression that diagnosis-resolved source ideas still win before
  transform-corpus fallback and blind declaration-pair fallback remains
  `non_actionable`;
- adapter tests converting focused `TransformProbe` fixtures to
  `LifetimeLayoutProbe` and preserving provenance, validating family filters,
  allowing record-only filters, applying total caps, de-duplicating identical
  candidate text, and producing file-safe labels;
- CLI/unit tests for lifetime-layout, coalesce-search, select-order-search,
  and frame-transform-search showing default probe lists unchanged, opt-in
  transform-corpus probes present, family filters honored, and JSON `probes`
  retaining top-level and provenance family metadata;
- compile-path tests where scoring is faked should show variants retain
  attached transform `probe` payloads;
- capability/catalog tests for transform-corpus discoverability and catalog
  drift;
- command-level smokes for help output and at least one `--no-compile-probes`
  or dry probe-list path that exercises real CLI parsing without invoking MWCC.

## Non-Goals

This integration does not add new mutator families, change semantic proof
guards, run transform-corpus probes by default in scorer commands, expand
`select-order-search --beam-depth` with corpus probes, or modify the external
`codex-rescue` plugin.
