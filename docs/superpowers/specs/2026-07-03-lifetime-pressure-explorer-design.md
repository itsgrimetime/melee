# Lifetime Pressure Explorer Design

Date: 2026-07-03
Status: Revised after review, awaiting user review before implementation plan

## Summary

Add `melee-agent debug inspect lifetime-pressure`, a read-only-by-default
diagnostic that explains MWCC register-allocation pressure in source-actionable
terms. Given a function, allocator facts, and a target allocation spec, the tool
reports why the current allocation happened, what blocks the expected physical
register, and which concrete source experiments should be validated next.

The command extends the current `mwcc-debug` inspection workflow. It does not
replace `first-divergence`, `virtual-to-var`, `lifetime-layout`,
`select-order-search`, `simplify-order`, or `score-source`; it composes those
tools into one higher-level pressure report.

The implementation must start by auditing and reusing the existing
`src.mwcc_debug.pressure_explorer` package. That package already owns
`PressureSignature`, `PressureDelta`, `pressure_signature_from_pcdump`,
`compare_pressure_signatures`, `generate_lifetime_layout_probes`, and
`generate_source_lifetime_probes`. The new command may refactor or extend that
package, but it must not create a parallel lifetime-pressure implementation
without first proving that the existing package cannot host the shared logic.

## Goals

- Work for any function with suitable allocator facts, not one hardcoded
  mismatch.
- Accept a current pcdump/source/function and a target allocation such as
  `--force-phys "53:25,50:22"`.
- Explain target virtuals/IGs, current versus expected physical registers,
  first definitions, source-variable attribution, compiler temps, live spans,
  interferers, blockers, simplify/select order, coalescing, spills, and why the
  current color was chosen.
- Produce ranked, concrete, source-level hypotheses and exact validation/search
  commands.
- Separate hard allocator facts from heuristic source guesses.
- Support human, JSON, optional DOT, and optional blocker-table outputs.
- Keep validation campaigns explicit, not default behavior.
- Protect all supplied target allocations by default during candidate
  validation.

## Non-Goals

- Do not parse retrowin32/gdb raw events or retail compiler structs. The retail
  tracer workstream owns that producer-side implementation.
- Do not claim source transforms are correct without compile/checkdiff or
  provided candidate evidence.
- Do not mutate repo source in default mode.
- Do not rely on raw IG ids across different compiles unless role descriptors
  or an explicit reanchor prove identity.
- Do not add a new candidate generator for validation. Validation must call or
  emit existing `debug target`, `debug mutate`, `debug select-order-search`,
  `debug permute`, and `debug inspect diff` workflows, with only thin
  orchestration in this command.

## Coordination With Retail Tracer

The retail MWCC backend/regalloc tracer thread owns exact GC/1.2.5n fact
collection and the producer schema. This explorer owns interpretation and
source-actionable synthesis.

The explorer will use an internal `AllocatorFacts` adapter with two inputs:

- MVP adapter: current `mwcc-debug` pcdumps, using existing colorgraph parsers,
  `first_divergence`, `virtual_attribution`, `tiebreak`, and pressure helpers.
- Future adapter: retail `backend-trace.v1.json` using the consumer-facing
  `functions[].regalloc.classes[]` subset.

The future retail adapter targets this normalized subset only. It will not
depend on `backend-events.v1.jsonl`, gdb breakpoint names, runtime addresses, or
raw retail struct layouts.

Shared schema constraints:

- Numeric `ig_id` and virtual ids are scoped to one compile.
- Cross-candidate comparison must use the existing role tooling:
  `role_descriptor.py`, `role_matcher.py`, and `role_reanchor.py`. Role
  descriptors use normalized first-def signatures, source attribution,
  block/instruction context, and symbol-bridge output; this command must not
  invent a second reanchor system.
- Required allocator facts for classes the function uses must be complete.
  Producer-side retail tracing should fail at confidence gates rather than emit
  degraded required facts.
- Source attribution may be `unattributed` or `ambiguous`; this explorer may
  enrich it and rank experiments, but the tracer does not own experiment
  ranking.

## Command Surface

Primary command:

```bash
melee-agent debug inspect lifetime-pressure -f FUNCTION
```

Core options:

```bash
--pcdump PATH                 baseline pcdump, auto-resolved when omitted
--source-file PATH            source file, auto-resolved when omitted
--force-phys SPEC             target allocation, e.g. 53:25,50:22
--target PATH                 target JSON/YAML, including force_phys and class ids
--candidate LABEL=PATH        repeatable pcdump/source candidate for comparison
--backend-trace PATH          future retail backend-trace.v1.json input
--class CLASS                 gpr/r/0, fpr/f/1, or auto
--allow-stale-pcdump          allow source-action guesses from stale pcdumps
--json                        emit machine-readable report
--dot PATH                    write target-centered interference subgraph
--blocker-table PATH          write compact blocker table
--validate MODE               none, quick, bounded, or remote
--timeout SECONDS             validation budget for explicit modes
--max-candidates N            candidate cap for explicit bounded validation
```

Default behavior is equivalent to `--validate none`.

Target behavior is deliberately not implicit:

- With `--force-phys` or `--target`, the command performs blocker analysis,
  source-action hypothesis ranking, and validation-command generation.
- Without a target, the command emits an inventory-only allocator pressure
  report: nodes, assignments, live ranges, interferers, coalesce/spill/order
  facts, and suggested commands for deriving a target. It must not claim a
  first blocker or emit source-transform hypotheses because there is no expected
  physical register to explain.
- A future explicit option may derive a target from register-only checkdiff
  using existing target helpers, but v1 should not silently infer one.

## Input Model

The analysis engine consumes normalized allocator facts, not parser-specific
objects. The internal model contains:

- Function metadata: function name, source path, pcdump or trace provenance,
  compiler identity, schema/source freshness warnings.
- Blocks: ids, order, successors, predecessors, labels.
- Per register class: class id/name, allocatable registers, initial volatile
  pool, nonvolatile dispense order, reserved/model-boundary registers.
- Nodes: IG id, virtual register kind/number, first-def site, live blocks,
  intervals when available, degree, flags, coalesce root/aliases, simplify
  order, select/color order, assigned physical, spill state, source attribution.
- Edges: interference pairs with confidence.
- Color decisions: iteration, assigned phys, candidate phys before choice,
  blockers, decision rule, confidence.

Minimal normalized shape:

```json
{
  "schema_version": "allocator-facts.v1",
  "producer": {"kind": "mwcc-debug-pcdump", "path": "BASE.pcdump.txt"},
  "function": {
    "name": "FUNCTION",
    "source_path": "src/...",
    "freshness": {
      "status": "fresh|stale|unknown",
      "pcdump_mtime": null,
      "source_mtime": null
    }
  },
  "classes": [
    {
      "class_id": 0,
      "class_name": "gpr",
      "registers": {
        "physical_count": 32,
        "allocatable": [3, 4, 5],
        "initial_volatile": [3, 4, 5],
        "nonvolatile_dispense_order": [31, 30, 29],
        "reserved": [1, 2]
      },
      "nodes": [
        {
          "ig_id": 32,
          "virtual": {"kind": "r", "number": 32},
          "first_def": {
            "pass_id": "before_register_coloring",
            "block_id": "B1",
            "instruction_id": "B1:0",
            "opcode": "lwz",
            "operands": "r32,0(r3)",
            "normalized": "lwz r#,0(r#)"
          },
          "source_attribution": {
            "status": "unattributed|attributed|ambiguous",
            "symbol": null,
            "line": null,
            "confidence": "unavailable"
          },
          "live": {"blocks": ["B1"], "intervals": [], "confidence": "observed"},
          "degree": 0,
          "flags": [],
          "coalesce": {"root_ig_id": 32, "aliases": []},
          "simplify_order": 0,
          "select_order": 0,
          "assigned_phys": 31,
          "spill": {"spilled": false, "reason": null}
        }
      ],
      "edges": [{"a": 32, "b": 35, "kind": "interference", "confidence": "observed"}],
      "coalesce": {"mappings": []},
      "simplify_order": [32, 35],
      "select_order": [35, 32],
      "color_decisions": [
        {
          "ig_id": 32,
          "iter": 1,
          "assigned_phys": 31,
          "node_state_before_select": {
            "degree": 1,
            "spill_flag": false,
            "coalesce_root_ig_id": 32,
            "assigned_before": null
          },
          "volatile_pool_before": [3, 4, 5],
          "nonvolatile_pool_before": {
            "dispensed": [31],
            "fresh_remaining": [30, 29]
          },
          "reserved_or_precolored_filtered": [1, 2],
          "available_phys_ordered": [31, 30],
          "blocked_candidates": [
            {"phys": 30, "blocked_by": [{"ig_id": 35, "phys": 30}]}
          ],
          "candidate_phys_ordered": [31, 30],
          "chosen_source": "available_pool|nonvolatile_dispense|spill",
          "decision_rule": "lowest_available_or_nonvolatile_dispense",
          "tie_rule": "lowest_available_then_nonvolatile_order",
          "confidence": "observed"
        }
      ]
    }
  ],
  "adapter_specific": {}
}
```

Required fields for v1: `schema_version`, `producer`, `function.name`,
`function.freshness.status`, `classes[].class_id`, `classes[].class_name`,
`classes[].registers`, `classes[].nodes`, `classes[].edges`,
`classes[].coalesce`, `classes[].simplify_order`, `classes[].select_order`, and
`classes[].color_decisions`.

Required per node: `ig_id`, `virtual`, `first_def`, `source_attribution`,
`live`, `degree`, `flags`, `coalesce`, `simplify_order`, `select_order`,
`assigned_phys`, and `spill`. Values may be `null` only when the adapter can
prove the fact is optional for the current class or node; otherwise the target
entry must abstain with a reason.

Required per color decision: `ig_id`, `iter`, `assigned_phys`,
`available_phys_ordered`, `blocked_candidates`, `candidate_phys_ordered`,
`chosen_source`, `decision_rule`, `tie_rule`, and `confidence`. Retail traces
should fill the richer decision-state fields (`node_state_before_select`,
`volatile_pool_before`, `nonvolatile_pool_before`, and
`reserved_or_precolored_filtered`) from observed compiler state. The
`mwcc-debug` pcdump adapter may synthesize or omit those richer state fields
only if it marks their confidence and abstains from conclusions that require
missing state.

Optional or adapter-specific fields belong under `adapter_specific` or clearly
named optional subkeys. Retail-tracer RE confidence details stay in the retail
trace; the explorer consumes only the normalized confidence summaries.

The `mwcc-debug` MVP adapter builds this from:

- `colorgraph_parser.parse_hook_events`
- `first_divergence` replay/classification helpers
- `virtual_attribution.explain_virtuals`
- `tiebreak.build_ig` and SELECT what-if helpers
- existing pressure signatures where candidate comparison is requested
- `pressure_explorer` data structures and comparison helpers for frame, saved
  register, spill, interference, coalesce, and target-pair deltas

## Target Resolution

The v1 target forms are:

- `--force-phys "IG:PHYS,IG:PHYS"` using the active class unless an entry
  includes a class prefix.
- Target JSON/YAML with function, class id, force-phys map, and optional
  baseline provenance.

Targets are compile-scoped by default. If the user compares candidates whose
raw IG ids drift, the report must mark those rows as compile-scoped and either
abstain or use `role_descriptor`/`role_matcher`/`role_reanchor` if descriptors
are available. No cross-compile raw id match should be presented as fact.

Every supplied target is protected by default. Candidate-level status is separate
from per-hypothesis evidence:

- `full_target_match`: all protected assignments satisfy the target spec and
  guard/frame checks pass.
- `partial_progress`: at least one protected target moves in the intended
  direction, no protected target regresses, and remaining misses are still
  wrong, unchanged, or not safely comparable.
- `rejected`: any protected target regresses, guard/frame checks fail, or the
  identity for a claimed win cannot be trusted.

Per-hypothesis status may be `supported` when its local target moved in the
intended direction without protected regressions, but that is not a validated
fix unless the candidate-level status is `full_target_match`.

## Analysis Pipeline

For each target node:

1. Resolve current node state: assigned physical, expected physical, spill
   state, coalesce root, aliases, simplify/select order, live span, first def,
   and source attribution.
2. Reconstruct allocator pressure:
   - registers available at the decision point;
   - registers blocked by direct interferers;
   - direct holder of the expected physical register;
   - lower-priority holders that must become unavailable for the target choice;
   - sticky nonvolatile pool state;
   - whether the target was coalesced away or spilled before coloring.
3. Classify the blocker:
   - interference blocks expected phys;
   - order/simplify/select position gives another node first choice;
   - sticky nonvolatile dispense state differs;
   - coalesce removes the target as an independent node;
   - spill or incomplete rows prevent reliable explanation;
   - no pressure issue when current equals target.
4. Rank blockers by impact:
   - direct expected-phys holder first;
   - lower-priority blockers next;
   - upstream order/dispense blockers;
   - coalesce roots and aliases;
   - spill/incomplete facts as hard blockers.
5. Generate source-action hypotheses and validation commands.

If the allocator facts are stale relative to the source file, source-action
hypotheses must either abstain or carry a prominent stale-facts warning unless
the user passes `--allow-stale-pcdump`. The allocator facts may still be shown
as historical facts, but source advice tied to current line numbers is unsafe
when the pcdump predates the source. Even with `--allow-stale-pcdump`, exact
line-numbered source actions must be suppressed or marked
`stale_line_mapping`; the override may enable generic source-family hypotheses
but not authoritative line-specific edits.

The report must preserve the distinction between:

- `allocator_fact`: mechanically derived from pcdump or backend trace.
- `source_guess`: heuristic mapping from node to source variable/expression.
- `validation_evidence`: compile/checkdiff/candidate evidence.

## Source Attribution

Reuse `virtual_attribution` as the primary source bridge. It already explains:

- declared locals and scope/confidence;
- field loads;
- global loads;
- call returns and copy chains;
- FPR expression order;
- compiler-introduced temps from first-def opcode.

When no source variable maps cleanly, the explorer reports the compiler-temp
kind and first-def operation instead of inventing a local name. Examples:

- `li` literal temp;
- `mr` copy/coalesce product;
- load/store-address temp;
- compare temp;
- implicit arithmetic/index temp;
- FPR expression temp;
- call-return copy chain.

Every source attribution includes confidence. Source lines are used for
actionable hints only when available.

## Hypothesis Generation

Hypotheses are ranked source experiments, not success claims. Each item
includes:

- target IG/virtual;
- source owner or compiler-temp description;
- allocator requirement, such as "remove edge X/Y" or "move X later";
- source action, such as shortening lifetime, extending lifetime, scoped temp,
  declaration movement, expression materialization, expression dematerialization,
  coalesce avoidance, or coalesce introduction;
- confidence;
- exact validation/search commands.

Example command routes:

```bash
melee-agent debug target score-source CANDIDATE.c -f FUNCTION --target TARGET --checkdiff-guard --json
melee-agent debug mutate lifetime-layout -f FUNCTION --pcdump BASE.pcdump.txt --source-file SRC.c --pairs rX/rY --json
melee-agent debug select-order-search -f FUNCTION --target rX<rY --force-phys IG:PHYS --pcdump BASE.pcdump.txt --source-file SRC.c --json
melee-agent debug mutate simplify-order -f FUNCTION --force-phys IG:PHYS --source-file SRC.c --pcdump BASE.pcdump.txt --json
melee-agent debug inspect diff BASE.pcdump.txt CANDIDATE.pcdump.txt -f FUNCTION
```

The command generator should choose existing tools rather than create a second
mutation workflow.

Generated command strings must be covered by tests against current CLI surfaces.
At minimum, golden command tests must cover `debug target score-source`,
`debug mutate lifetime-layout`, `debug select-order-search`,
`debug mutate simplify-order`, and `debug inspect diff`.

## Validation Modes

Default mode is read-only and emits commands only.

Explicit modes:

- `--validate quick`: run cheap scoring on supplied candidates or a small
  generated probe set. It may compile temporary candidates but must restore
  source and report guard/frame/register regressions.
- `--validate bounded --timeout 120 --max-candidates 500`: run bounded local
  candidate generation/scoring through existing workflows.
- `--validate remote --timeout 3600`: v1 is dry-run/emit-only by default. It
  emits the remote-safe long campaign command set, required campaign/output dir,
  timeout, expected state/log files, and triage commands. It does not launch
  expensive remote campaigns unless a future explicit launch flag is added.
  If remote support is not available for a selected route, the report emits the
  blocker and local alternatives.

Validation output never overwrites the default fact/guess split. A hypothesis
becomes `supported` only when compile/checkdiff or supplied candidate evidence
shows its local target moved in the intended direction and no protected target
regressed. Candidate-level validation uses the status taxonomy from Target
Resolution: `full_target_match`, `partial_progress`, or `rejected`.

## Candidate Comparison

`--candidate LABEL=PATH` accepts these v1 forms:

- `LABEL=path/to/candidate.pcdump.txt` or `LABEL=path/to/candidate.txt`:
  read-only comparison against an already-captured pcdump.
- `LABEL=path/to/candidate.c`: rejected in read-only mode because comparing it
  requires compilation. Accepted only in compile-capable validation modes
  (`quick` or `bounded`, or a future explicit remote launch flag). With
  `--validate remote` in v1, source candidates are not compared evidence; the
  report emits remote dry-run commands for that source instead.
- Paired source+pcdump evidence is not implicit in v1. If added later, it must
  use an explicit syntax so the default path cannot accidentally compile or
  associate the wrong source with a pcdump.

Comparison reports:

- target hit/miss and distance change;
- first changed allocator fact;
- live-range/interference/coalesce/simplify/select deltas;
- whether one target improves while another worsens;
- guard/frame/match-percent evidence when available;
- commands to score missing evidence.

Raw IG id comparisons across candidates are marked unsafe unless existing role
reanchor tooling aligns them.

## Human Report

Default text output is organized as:

1. Header and input provenance.
2. Target summary.
3. "No pressure issue" summary when all targets already match.
4. Per-target allocator facts.
5. Blocker table sorted by impact.
6. Source attribution and compiler-temp explanation.
7. Ranked hypotheses.
8. Exact validation/search commands.
9. Candidate comparison deltas.
10. Warnings and abstentions.

Warnings must be concrete: stale pcdump, missing source, target absent, target
coalesced away, incomplete interferer row, model-boundary register, source
attribution ambiguous, or cross-compile identity unsafe.

## JSON Report

`--json` emits a stable object:

```json
{
  "schema_version": "lifetime-pressure-report.v1",
  "function": "FUNCTION",
  "inputs": {},
  "targets": [],
  "allocator_facts": {},
  "blockers": [],
  "source_attribution": {},
  "hypotheses": [],
  "validation_commands": [],
  "candidate_comparisons": [],
  "outputs": {},
  "warnings": []
}
```

Per-target entries include validation status. Optional fields are `null` only
when genuinely unavailable; unsupported required allocator facts produce a
warning or an abstained target entry rather than silent omission.

## DOT And Blocker Table

`--dot PATH` writes a target-centered interference graph:

- target nodes highlighted;
- expected-phys blockers highlighted;
- lower-priority blockers grouped;
- coalesce aliases drawn to roots;
- spills marked distinctly.

`--blocker-table PATH` writes CSV or JSON based on extension. Rows include:

- target IG/virtual;
- blocker IG/virtual;
- blocker assigned phys;
- blocker type;
- source attribution summary;
- impact score;
- suggested lever;
- validation command id.

## Error Handling

Hard errors:

- function missing from pcdump/trace;
- malformed target spec;
- target function mismatch in saved target;
- requested class missing when the function uses that class;
- source candidate supplied in read-only mode where compilation would be needed.

Abstentions:

- incomplete interferer row;
- model-boundary register such as r0 when existing replay refuses it;
- coalesced-away target without enough alias/root evidence;
- spill state that cannot be tied to simplify/color facts;
- cross-candidate identity mismatch without role descriptor.
- stale pcdump for source-action hypotheses unless the report can clearly
  separate historical allocator facts from current source advice or the user
  passes `--allow-stale-pcdump`.

The command should prefer a partial report with explicit abstentions over a
misleading complete-looking explanation.

## Validation Cases

Required test or smoke coverage:

- Matched/no-pressure case: use a function where target equals current and
  expect "no pressure issue".
- Known register-allocation-only mismatch: use an existing fixture such as
  `lbDvd_80018A2C` or another current high-percent regalloc residual.
- Stress case: `mnDiagram_UpdateScrollArrows` if present, otherwise resolve the
  current symbol/source name and document the mapping. This case must emphasize
  that attractive source advice is unvalidated until real-tree guards and
  allocator-state preservation pass.

Unit tests:

- force-phys and target file parsing;
- `mwcc-debug` `AllocatorFacts` adapter;
- target node report;
- blocker ranking;
- source-attribution classification;
- compiler-temp explanation;
- command generation;
- JSON schema stability;
- DOT output shape;
- candidate comparison with target improvement and protected-target regression.
- round-trip role reanchoring through `role_descriptor`, `role_matcher`, and
  `role_reanchor`, including a case where raw IG ids drift and a case where
  identity is not stable enough to compare.
- stale pcdump/source freshness handling that suppresses or prominently warns on
  source-action hypotheses.
- generated validation command golden tests for every supported route.

CLI tests:

- `debug inspect lifetime-pressure --help` golden.
- fixture pcdump JSON smoke.
- read-only default does not compile or edit source.
- explicit validation mode restores source after temporary scoring.
- future retail adapter fixture smoke: consume a checked-in minimal
  `backend-trace.v1.json` consumer-contract fixture from the retail tracer
  workstream, or prove that the explorer's `allocator-facts.v1` example maps
  cleanly from that fixture.

## Documentation

Add examples to the `mwcc-debug` docs near existing inspect commands:

```bash
melee-agent debug inspect lifetime-pressure \
  -f mnDiagram_UpdateScrollArrows \
  --force-phys "53:25,50:22"

melee-agent debug inspect lifetime-pressure \
  -f lbDvd_80018A2C \
  --pcdump tools/melee-agent/tests/fixtures/mwcc_debug/lbDvd_80018A2C_pcdump.txt \
  --force-phys "44:10,46:12" \
  --json

melee-agent debug inspect lifetime-pressure \
  -f FUNCTION \
  --force-phys "53:25" \
  --validate bounded --timeout 120 --max-candidates 500
```

The docs must repeat the main safety rule: default source advice is heuristic
until validated by compile/checkdiff or supplied candidate evidence.

## Implementation Boundaries

Start from the existing `src.mwcc_debug.pressure_explorer` package. Before
creating any new lifetime-pressure package, audit whether the new fact adapter,
analysis, hypothesis, and render code belongs as refactored modules under
`pressure_explorer`. A separate package is allowed only if the implementation
plan documents why sharing the package would create worse boundaries.

Likely boundaries, preferably under `src.mwcc_debug.pressure_explorer`:

- fact loading / normalized `AllocatorFacts` adapter;
- allocator analysis;
- source hypothesis generation;
- rendering / JSON / DOT / blocker table;
- `src.cli.debug.inspect` command wiring

The exact module split may follow existing local patterns, but the boundaries
should remain fact loading, allocator analysis, source hypothesis generation,
rendering, and CLI orchestration. Validation integration must remain a thin
caller or command emitter over existing workflows; it must not grow independent
probe families that duplicate `pressure_explorer`, transform-corpus,
select-order, simplify-order, or permuter routes.

## Success Criteria

- A user can run one command for a function and target allocation and receive a
  source-actionable pressure report.
- The first meaningful blocker is identified in live-range/interference/order
  terms, not merely as "register allocation differs".
- The report emits concrete validation/search commands.
- Candidate comparisons explain why a candidate moved closer or farther from
  the target.
- Default mode is read-only and does not edit source or launch long campaigns.
- JSON/DOT/blocker-table outputs are stable enough for other tools to consume.
