# Generated Pointer-Walk Node-Set Handoff

## Context

Issue 921 reports a concrete failure in the copy-survived coalesce repair flow for
`mnDiagram_SortNamesByKOs`. A retained source candidate introduces or exposes a
nested generated pointer-walk local such as `ll_probe_iter_0`, and the handoff
correctly suggests `node-set-split --var ll_probe_iter_0`. The node-set layer then
reports `no-source-probes` because its current alias and lifetime mutators only
work from normal read sites. This generated local is used in a loop-header
increment and a dereferenced store, so those mutators intentionally have no safe
read anchor.

The same flow also drops exact force-phys context. A coalesce search may be run
with `--transform-force-phys 34:27,44:25`, but the generated node-set command
only carries the primary `--ig` and `--target-reg`. Wrong-register node-set rows
therefore lack a full `target_score.virtuals` map for both 34 and 44, which makes
progress invisible.

## Design

Add a narrow generated pointer-walk source family inside `node_set_split`. When
the request variable matches `ll_probe_iter_<n>`, find a simple pointer local
declaration in the target function:

```c
u8* ll_probe_iter_0 = dst;
```

If the initializer is a simple local and that local has a safe initializer in the
same function before the generated local declaration, emit a candidate that
rewrites only the generated local initializer:

```c
u8* ll_probe_iter_0 = mnDiagram_804A076C.sorted_names;
```

This is intentionally not a general expression-rewrite engine. It only follows a
single source-visible pointer alias and only accepts side-effect-free initializer
expressions with no calls, assignments, comma expressions, or increments.

Add exact force-phys evidence to `node-set-split`. The command accepts a
`--force-phys` option, with `--transform-force-phys` as a compatibility alias for
handoffs from coalesce search. When present, every compiled node-set candidate
gets an `objective.target_score` map with expected, actual, hit, matched, and
distance values for each requested IG. The existing node-set objective still
drives candidate status, but the retained wrong-register rows now expose the
full evidence needed for the next repair lane.

Update coalesce continuation routes so generated node-set commands preserve the
original transform force-phys map. The route remains source-actionable against
the retained `.c` candidate and still includes the primary `--ig` and
`--target-reg`.

## Tests

Regression coverage should include:

- `generate_node_set_split_patches` emits a generated-pointer-walk direct-base
  candidate for `ll_probe_iter_0`.
- The CLI no longer reports `no-source-probes` for this generated local when the
  targeted initializer rewrite is available.
- `node-set-split --force-phys 34:27,44:25` surfaces
  `candidate.target_score.virtuals` for wrong-register retained candidates.
- Coalesce continuation commands include the force-phys map on generated-local
  node-set routes.

## Risks

The main risk is over-matching source that is not a simple pointer alias. The
helper avoids that by requiring a generated-local name, a single local
initializer, and a safe base initializer. If the source is more complex, the
existing terminal blocker and fallback variable reporting remain available.
