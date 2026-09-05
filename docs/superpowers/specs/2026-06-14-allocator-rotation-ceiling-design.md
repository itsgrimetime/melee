# Allocator Rotation Ceiling Classifier Design

## Goal

Issue #704 reports that the mndiagram coloring-register workflow has reached a
terminal-looking state: force-phys, solve-coloring, coupled node-set-split, and
transform-corpus steering all engage, but every source-shape attempt stays
wrong-register or negative-evidence. The next useful capability is below the
source-shape layer: agents need one command that can read the existing evidence
and classify the run as either still actionable, bounded/incomplete, or a
practical target-only allocator ceiling.

This feature does not add another source mutator. It adds a conservative
evidence classifier so agents stop rerunning exhausted source-shape families and
know exactly which missing proof prevents a ceiling verdict.

## Approaches Considered

1. Add more `coloring_register_steering` source families. This is not selected:
   #704 explicitly says all six current source-shape approaches have fired and
   none moved the group toward a byte match.
2. Add a backend override that directly forces MWCC allocator tie-breaks. This
   might eventually produce deeper proof, but it is invasive and risks changing
   the debug DLL before we have a durable user-facing triage surface.
3. Add a data-driven ceiling classifier over existing JSON outputs. This is
   selected because it is small, auditable, testable without live compiles, and
   creates the missing "below source-shape" routing layer.

## Selected Design

Add a pure helper module:

```text
tools/melee-agent/src/mwcc_debug/allocator_ceiling.py
```

The module exposes `classify_allocator_ceiling(evidence: list[dict]) -> dict`.
Each evidence dict is an existing JSON payload from one of these commands:

- `debug solve coloring --json`
- `debug solve node-set-split --json`
- `debug search plan-transforms --json`
- `debug target force-phys-from-diff --json`

The classifier recognizes only durable schema fields already emitted by those
commands:

- solve-coloring `node_set_delta.blocker == "structurally-different-virtual"`
- node-set-split `wrong_register_exhausted == true`
- transform-corpus validation summaries with no retained or byte-match
  candidates and exhausted/negative evidence outcomes
- force-phys verification summaries, required for a ceiling verdict
- any positive proof: `byte_match`, `status == "improved"`,
  positive `best_checkdiff_delta`, or retained validation candidate

## CLI

Add `melee-agent debug solve allocator-ceiling`:

```bash
melee-agent debug solve allocator-ceiling \
  --function mnDiagram2_Create \
  --evidence solve.json \
  --evidence node-set.json \
  --evidence transforms.json \
  --json
```

The command is intentionally read-only. It loads one or more JSON evidence
files, calls the helper, and exits:

- `0` when the classifier finds a positive proof,
- `2` when evidence is invalid, unreadable, malformed, or scoped to the wrong
  function,
- `3` when evidence proves a practical ceiling, or is incomplete and the next
  action is to gather more proof,
- `4` when evidence is still bounded by candidate limits, budgets, or omitted
  source probes.

Text output prints the verdict, terminal reason, evidence items, and next
commands. JSON output includes:

- `status`: `actionable`, `practical-ceiling`, `incomplete`, or `bounded`
- `terminal_reason`
- `positive_proofs`
- `source_shape_exhausted`
- `node_set_delta`
- `wrong_register_exhausted`
- `bounded_reasons`
- `missing_evidence`
- `next_steps`

The command accepts a solve-coloring wrapper or a bare nested payload. Evidence
files may contain a single JSON object or a list of objects.

Every evidence object must be scoped to `--function`. The classifier accepts
function names from top-level `function`, nested `node_set_delta.function`,
`plan.function`, and per-summary function fields. If any scoped object names a
different function, the CLI rejects the input with exit code `2`; mixed-function
evidence must never contribute to either a positive proof or a ceiling verdict.

## Verdict Rules

Positive proof wins. If any evidence reports a byte match, retained validation
candidate, improved node-set split, or positive checkdiff delta, the status is
`actionable`; this is not a ceiling.

Bounded evidence is not a ceiling. Candidate-limit, budget-exhausted, or omitted
source-shape candidates produce `bounded` with a next step to rerun using
larger bounds. Transform-corpus `exhausted-negative-evidence` counts as
complete only when `remaining_probe_ids` is empty and
`node_set_delta_summary` has no `omitted_count` or `capped_count`.
`skipped_count` is not a bound by itself: it records unbindable evidence that
the source layer cannot express, and should be surfaced in the ceiling payload.

Complete negative evidence plus node-set proof is a practical ceiling:

1. solve-coloring emitted a structurally-different-virtual node-set delta,
2. force-phys verification ran and its union proof is a clean `match`,
3. node-set-split evidence is exhaustive and all compiled objectives are
   wrong-register, and
4. transform-corpus validation is exhausted negative evidence with no retained
   candidate or byte match.

If some of those proofs are absent, the status is `incomplete` and the command
prints the exact evidence file to gather next.

`practical-ceiling` is a solve abstain, not a success. Exit codes:

- `0`: actionable positive proof found
- `2`: invalid evidence, unreadable file, malformed JSON, or function mismatch
- `3`: practical ceiling or incomplete proof
- `4`: bounded proof that should be rerun with larger limits

## Safety And Scope

The classifier never edits source, never compiles candidates, and never resolves
an issue by itself. It only names the routing. It should not parse free-form log
text; all inputs must be structured JSON.

The feature should not close #699 unless a real validation still satisfies
#699's byte-match stop condition. #704 can be resolved when the classifier is
implemented, tested, and a command-level smoke check shows it classifies the
reported exhausted evidence as `practical-ceiling`.

## Tests

- Unit tests for positive proof precedence.
- Unit tests for bounded candidate-limit and budget outcomes.
- Unit tests for incomplete evidence with actionable missing-evidence messages.
- Unit tests for mixed-function rejection across single objects and list
  payloads.
- Unit tests for missing, failed, and inconclusive force-vector verification.
- Unit tests that distinguish transform-corpus `skipped_count` from
  `omitted_count` and `capped_count`.
- Unit tests for practical ceiling from solve-coloring node-set delta,
  clean force-vector proof, node-set-split all-wrong-register, and
  transform-corpus exhausted-negative evidence.
- CLI tests for multiple `--evidence` files, list payload flattening, JSON
  output, text output, and missing/invalid files.
- A command-level smoke using synthetic #704-style evidence.

## Independent Review Criteria

An independent reviewer should check that the classifier is conservative, does
not silently turn bounded evidence into a ceiling, and does not overlap with the
existing source-shape probe generators.
