# FPR Node-Set Split Support

## Context

Issue #705 reports that `debug solve coloring --class fpr` can reach the same
`structurally-different-virtual` blocker as the GPR path, but the concrete
node-set split vocabulary is still shaped around GPR cases. The reported
function, `mnDiagram_80241E78`, has a small FPR residual involving swapped
callee-save FPRs. The solver can emit `node_set_delta` evidence for class 1,
and `debug solve node-set-split --node-set-delta` already accepts `--class fpr`
and infers the class from the delta. The main gap is the source candidate
generator: commit `8d9aa6720` deliberately gated reassociation candidates to
GPR because the existing matcher was syntax-only and allowed integer literals.

## Goal

Make class-1 node-set split evidence produce useful, bounded source worksheets
without adding a new command. The success path is:

1. `debug solve coloring --class fpr --json` emits class-1 `node_set_delta`
   evidence for structural virtual blockers.
2. `debug solve node-set-split --node-set-delta <json>` consumes that evidence,
   infers class 1, and evaluates generated candidates against class-1 pcdump
   signatures.
3. `debug search plan-transforms --node-set-delta <json>` can materialize the
   same FPR split candidates through the transform-corpus path.
4. For #705 specifically, at least one `mnDiagram_80241E78` class-1 delta
   produces concrete FPR node-set split candidates, and a live worksheet either
   improves match percentage by at least 0.1 percentage points or provides
   bounded negative evidence across the FPR candidate set.

## Non-Goals

- Do not add a new CLI command or new solver mode.
- Do not claim floating addition operand swaps are semantically equivalent in
  all C/IEEE edge cases. These are decompilation search probes and remain
  gated by compile/objective/checkdiff validation.
- Do not relax field-expression, indexed-expression, call, cast, or multi-term
  arithmetic guards for FPR in this change.
- Do not apply a candidate by default. `--apply-best` remains explicit and only
  applies an already verified improvement.

## Approaches Considered

### 1. Remove the FPR Reassociation Gate

This is the smallest patch, but it would let class-1 requests use the current
syntax-only reassociation matcher. That matcher accepts integer literals and
does not verify operand types. It risks emitting misleading FPR candidates for
mixed integer/float expressions. Rejected.

### 2. Add a Separate FPR-Safe Reassociation Path

Keep GPR behavior unchanged. For class 1, allow reassociation only when the
assignment is exactly a simple identifier assignment whose left-hand side and
both operands resolve to unambiguous function-local or parameter declarations
with floating scalar type (`float`, `f32`, `double`, or `f64`). Reject literals,
casts, calls, member/index access, nested operators, ambiguous duplicate names,
and unsupported declaration shapes. This is the chosen design.

### 3. Skip Reassociation and Rely Only on Alias/Lifetime/Decl-Order

This avoids floating arithmetic concerns, but the existing issue points at FPR
virtual splits where operand order and temporary shape can matter. It would
leave `mnDiagram_80241E78` with no new useful vocabulary. Rejected.

## Design

### Candidate Generation

`generate_node_set_split_patches` continues to call `_append_reassociation_patches`
after alias, lifetime, declaration-order, and per-loop rename candidates. The
helper becomes class-aware:

- `class_id == 0`: preserve existing GPR reassociation behavior, including the
  current simple identifier/integer-literal operand rules.
- `class_id == 1`: use a new typed FPR admission guard before appending a
  reassociation patch.
- other classes: emit no reassociation candidates.

The FPR guard builds a declaration map for the requested function from
`_parse_params` and `walk_local_decls`. A name is admissible only if exactly one
declaration exists for that name in the function-level parsed declarations and
its normalized type is one of `float`, `f32`, `double`, or `f64`, allowing
qualifiers such as `const` and `volatile`. If any of the assignment target or
operands is missing, duplicated, pointer-like, array-like, struct-like, or
non-floating, the candidate is rejected.

The existing expression parser still enforces one top-level `+` and simple
identifier operands. Because `_is_simple_reassociation_operand` currently also
accepts integer literals for GPR, the FPR path must additionally require both
operands to be identifiers found in the FPR declaration map.

### Real-Source Coverage

Add a regression fixture using a small `mnDiagram_80241E78`-shaped source slice
that includes `f32` locals and a class-1 delta. The test should prove that:

- `requests_from_node_set_delta` preserves `class_id == 1` and `f*` registers.
- `generate_node_set_split_patches` emits at least one class-1 candidate for a
  bindable FPR local in the source slice.
- blocked source forms for the same delta remain blocked when the variable is
  unbindable or not declared.

This fixture is intentionally local and compiler-free. Live smoke checks will
cover the real CLI path.

### CLI Routing

`debug solve node-set-split --node-set-delta` already infers `class_id` from the
delta before compiling signatures. Add a regression that monkeypatches the
compile-signature helper and asserts both baseline and candidate calls receive
`class_id == 1` when the delta is class 1 and no explicit `--class` is supplied.

`debug solve coloring --class fpr --json` already preserves `node_set_delta`.
Add a narrow regression around `_derive_node_set_delta_payload` or the CLI
wrapper that asserts class 1 produces `register_prefix == "f"` and desired
register strings such as `f28`.

### Transform-Corpus Bridge

The existing `plan-transforms --node-set-delta` path wraps `node_set_split`
`CandidatePatch` output. Add an FPR smoke/regression that feeds a class-1 delta
and asserts the resulting probe payload carries class 1 and `f*` register
targets. The delta owns node-set probe class; if a separate `--force-phys`
class is also supplied, do not reinterpret the delta as GPR.

## Testing

Focused tests:

- `tools/melee-agent/tests/test_node_set_split.py`
  - FPR reassociation emits for `float`, `f32`, `double`, and `f64` locals.
  - FPR reassociation rejects integer literals, float literals, mixed int/float
    operands, casts, calls, member/index access, duplicate declarations, and
    `a + b + c`.
  - Class-1 node-set delta requests preserve FPR class and registers.
  - A `mnDiagram_80241E78`-shaped class-1 delta materializes candidates.
- `tools/melee-agent/tests/search/solver/test_cli_solve.py`
  - `node-set-split --node-set-delta` infers class 1 for compile signatures.
  - `solve coloring --class fpr --json` includes class-1 delta metadata.
- `tools/melee-agent/tests/search/test_cli_smoke.py` or existing transform
  tests
  - `plan-transforms --node-set-delta` preserves class-1 probe metadata.

Command-level checks:

- Focused pytest for node-set split, solve CLI, and transform CLI tests.
- `python -m compileall -q tools/melee-agent/src`
- `git diff --check`
- Installed `melee-agent debug solve node-set-split --help`
- Live `mnDiagram_80241E78` smoke using `solve coloring --class fpr --json`
  followed by bounded `node-set-split --node-set-delta`.

## Acceptance Criteria

- #705 is resolved only if class-1 node-set split evidence now yields a ranked
  worksheet/candidate set for `mnDiagram_80241E78`, and the run records either
  a match-percentage improvement of at least 0.1 points or bounded negative
  evidence after evaluating the FPR candidate vocabulary.
- Existing GPR node-set split tests continue to pass unchanged.
- The editable `/opt/homebrew/bin/melee-agent` install imports current master
  after the change.
