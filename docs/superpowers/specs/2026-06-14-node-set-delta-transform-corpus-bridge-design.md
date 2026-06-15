# Node-set-delta Transform-corpus Bridge Design

## Goal

Issue #699 remains open because the concrete `coloring_register_steering`
families now engage on `mnDiagram2_Create`, but real validation still exhausts
negative evidence with no byte match. The latest useful diagnostic is no
longer "try another declaration-order nudge"; it is:

```text
force-phys collision: target coloring unreachable
(the escape is a structurally different virtual)
```

`debug solve coloring --json` already emits a `node_set_delta` payload for that
case, and `debug solve node-set-split --node-set-delta` can consume it. The
gap is that agents using the common `debug search plan-transforms` workflow do
not have a way to feed that evidence into transform-corpus, so they keep
receiving only blind rotate/demote/counter candidates.

The feature adds a bounded evidence bridge:

- `plan-transforms --node-set-delta PATH`
- `generate_transform_probes(..., node_set_delta=...)`
- materialized `coloring_register_steering` probes that wrap existing
  node-set-split patches.

Resolve #699 only if a generated candidate reaches the issue's byte-match stop
condition. If the bridge generates candidates and real validation remains
negative, leave #699 open with evidence.

## Approaches Considered

1. Add more blind declaration/counter steering families. This has already
   produced several compiled negative candidates, and the solver now says the
   missing value is a structurally different virtual.
2. Expand generic statement-order or source-shape anchors into the coloring
   cluster. This may eventually help, but it is not tied to the failing solver
   evidence and risks another noisy candidate stream.
3. Bridge solver `node_set_delta` evidence into transform-corpus using the
   existing guarded node-set-split patch generators. This is selected because
   it reuses tested source-shape machinery, gives agents a single
   `plan-transforms` validation path, and keeps the new candidate set bounded.

## Selected Design

### CLI

Add optional `--node-set-delta PATH` to `debug search plan-transforms`.

The option accepts either a bare `node_set_delta` payload or the full
`debug solve coloring --json` wrapper. When omitted, command behavior and JSON
shape remain unchanged except for the static catalog metadata changes.

When supplied, the command reads the JSON, passes it to
`generate_transform_probes`, and includes node-set-delta probe metadata in the
normal `probes`, `validation`, `validation_summary`, and ledger flows. It also
adds a top-level JSON field such as `node_set_delta_summary` whenever
`--node-set-delta` is supplied, because the all-unbindable case has no probe
payloads to carry skipped-entry evidence. The existing `--write-probes`,
`--validate-command`, and `--stop-on-retained` gates remain the only
command-level proof mechanism.

### Transform-corpus Integration

Extend `generate_transform_probes` with:

```python
node_set_delta: Mapping[str, object] | None = None
```

When the current plan allows `coloring_register_steering` and
`node_set_delta` is present, generate evidence-led probes before existing blind
steering probes:

1. Coupled node-set-split probes via
   `generate_coupled_node_set_split_patches`.
2. Single-request node-set-split probes via
   `generate_node_set_split_patches`.
3. Existing rotate/demote/counter/source-shape steering probes if budget
   remains.

Use `requests_from_node_set_delta(delta, source_text=source_text)` to obtain
bindable requests. Cap the coupled request set to a small deterministic prefix
(2 or 3 requests) and cap generated coupled candidates by `max_per_family`.
Use `max_read_sites=2` for single patches and `max_per_ig=3` for coupled
patches so default command runs stay bounded.

Wrap each existing `CandidatePatch` as a `TransformProbe`:

- `family_id`: `coloring_register_steering`
- `mutator_key`: `steer_node_set_delta_split` or
  `steer_node_set_delta_coupled_split`
- `candidate_text`: `patch.patched_source`
- `payload`: raw request dict(s), patch candidate id, hunk, source action,
  touched ranges, and skipped missing virtuals
- `target_assignments`: request-derived labels such as `ig36:r25->r27`,
  not just force-phys labels
- `span`: merged min/max touched range from `CandidatePatch.touched_ranges`,
  falling back to the full source only when the patch reports a full-source
  range

The new keys are materialized-candidate probe keys. They do not need
`apply_mutator()` dispatch because the wrapped node-set-split patch has already
produced the complete candidate source. Documentation and catalog wording must
say this explicitly.

### Skipped Evidence

Do not imply that every `missing_virtuals` entry was materialized. Some entries
are implicit temps or field expressions that `requests_from_node_set_delta`
cannot bind to a source declaration. The bridge records skipped entries in
probe payloads and in a lightweight top-level summary helper so JSON users can
see which virtuals remained unhandled.

If all entries are unbindable, no probes are emitted. The existing
`plan-transforms` no-probe and ledger paths then report blocked evidence
instead of silently succeeding.

## Safety Rules

This bridge does not add blind string rewrites. It delegates source edits to
the existing node-set-split generators:

- alias before use,
- lifetime preservation,
- declaration-order candidates,
- per-loop rename,
- simple GPR reassociation,
- bounded coupled compositions of those edits.

Those generators already parse and validate source shape before producing a
`CandidatePatch`. The bridge only dedupes fully materialized candidate text,
assigns transform-corpus provenance, and enforces the family budget.

The coupled path composes existing per-ig generators on each intermediate
source and prunes branches that no longer apply. This preserves the existing
safety model: a missed edit yields fewer candidates, not a wrong splice.

## Probe Ordering

Default-budget visibility matters. With `--node-set-delta`, default
`max_per_family=3` must not be consumed by blind rotate/demote/counter probes
before evidence-led probes run.

Ordering:

1. `steer_node_set_delta_coupled_split`
2. `steer_node_set_delta_split`
3. existing concrete steering probes:
   `steer_rotate_local_decl_window`,
   `steer_demote_local_decl_to_first_use`,
   `steer_reuse_dead_top_level_loop_counter`,
   `steer_split_reused_loop_counter`
4. existing aliased source-shape steering probes if budget remains

## Tests

Unit and CLI coverage:

- `generate_transform_probes` output is unchanged when `node_set_delta=None`.
- Bare node-set-delta and solve-coloring wrapper payloads are both accepted.
- One bindable request emits `steer_node_set_delta_split`.
- Two bindable requests emit coupled probes before blind steering probes under
  default budget.
- Unbindable implicit-temp and field-expression entries are reported in
  payload metadata instead of silently disappearing.
- Candidate text is deduped across node-set-delta and existing steering probes.
- `plan-transforms --node-set-delta --write-probes --validate-command --json`
  writes and validates materialized candidate files.
- Catalog metadata lists the two new materialized-candidate probe keys without
  claiming they are standalone `apply_mutator` dispatch keys.

Field validation:

Run installed CLI validation on the reporter `mnDiagram2_Create` delta:

```bash
melee-agent debug search plan-transforms \
  --function mnDiagram2_Create \
  --unit melee/mn/mndiagram2 \
  --force-phys <current-force-vector> \
  --node-set-delta <solve-coloring-json> \
  --write-probes <tmpdir> \
  --validate-command 'melee-agent debug dump local {candidate_path} --unit-source src/melee/mn/mndiagram2.c --function mnDiagram2_Create --diff --no-cache-sync' \
  --json
```

Resolve #699 only if validation reports a byte match. If the generated
node-set-delta candidates compile but do not byte-match, add the evidence to
#699 and release the claim.

## Independent Review

Review verdict: SHIP-WITH-CHANGES.

Changes incorporated:

- evidence-led probes must run before blind steering when `--node-set-delta`
  is supplied,
- skipped or unbindable missing virtuals must be visible,
- coupled composition must be defensively capped,
- target assignment labels must come from request current/target registers,
- catalog wording must distinguish materialized probes from mutator-dispatch
  keys,
- span metadata must be derived from `CandidatePatch.touched_ranges`.
