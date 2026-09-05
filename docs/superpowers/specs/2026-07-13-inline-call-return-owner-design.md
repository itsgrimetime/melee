# Inline call-return owner attribution

## Goal

Make the existing window-order call-return source planner materialize a bounded
source probe when compiler attribution names a low-level call return but the
source-visible owner is hidden behind one TU-local inline wrapper. The reported
case is the copy chain `r72 <- r86 <- r3`: `HSD_JObjLoadJoint` assigns the
wrapper-local `jobj`, the wrapper returns `jobj`, and the selected function
assigns the wrapper call to `header`.

This is an attribution extension, not a new search family or CLI. The existing
select-order campaign, retention, compilation, pcdump, and scoring machinery
remain authoritative.

## Evidence and existing capabilities

The retained campaign under
`build/select-order/fighter-direct-full-52-51-72` records IG 72 as a
`call-return` attribution with `call_symbol=HSD_JObjLoadJoint`, no source name
or type, and `copy_chain=[72, 86, 3]`. Its source contains:

```c
static inline HSD_JObj* mnDiagram_CreateFighterHeader(...)
{
    HSD_JObj* jobj;
    jobj = HSD_JObjLoadJoint(...);
    ...
    return jobj;
}

...
header = mnDiagram_CreateFighterHeader(...);
```

The existing `window_order_source` planner already finds visible local
assignments, resolves local pointer types, inserts a function-scope synthetic
local, emits exact source diffs/provenance, and bounds output by the campaign
probe limit. The inline-leverage tools already establish that TU-local inline
definitions and call sites are source-visible concepts. This change reuses
those boundaries and does not add another parser-facing command.

## Considered approaches

### A. Conservative inline-wrapper resolution in the existing planner

Recommended. When direct named call-return ownership fails, inspect only bare
wrapper-call assignments in the selected function. Prove a unique wrapper
definition, a unique direct low-level call assigned to a helper local, one
direct return of that same local, compatible pointer types, and an exact ABI
copy chain. Then pass the visible caller owner to the existing owner-split
materializer.

This preserves current orchestration, makes the retained case actionable, and
keeps the new semantic inference narrow and testable.

### B. Explicit owner override

Rejected. A user-supplied mapping from IG/call symbol to `header` would make the
campaign run, but it would bypass source proof, be stale when candidates
change, and violate exact provenance-or-abstain behavior.

### C. Rejection-only diagnostics

Rejected as the final behavior. Improving `call-return-owner-copy-not-found`
would help triage but would leave a uniquely provable source candidate
unmaterialized. The implementation still adopts concrete rejection reasons
from this approach for every chain it cannot prove.

## Resolution contract

The direct named-owner path remains unchanged. The wrapper fallback is eligible
only for a `call-return` attribution and must prove all of the following:

1. `copy_chain` is a bounded sequence of distinct integer virtual registers,
   begins with the requested target IG, and ends in ABI return virtual `3`.
2. The target function has one simple assignment whose RHS is a bare call to a
   TU-local helper that satisfies this contract.
3. The helper has exactly one definition and is explicitly `inline`; neither
   its definition nor the target assignment is under preprocessor control.
4. The helper body has exactly one direct call whose callee equals the
   attributed `call_symbol`.
5. That low-level call is the entire RHS of a simple assignment or declaration
   initializer to one plain helper-local identifier.
6. The helper has exactly one `return`, and its entire expression is that same
   local identifier. Intervening statements are allowed because the retained
   helper configures the returned object before returning it.
7. The helper return type, helper result-local type, and visible target-owner
   type are all source-resolved pointer types and normalize identically. A
   non-null attribution type must also agree.
8. The helper definition, low-level call, return, owner declaration, and target
   assignment have unique source spans. Macro-like, compound, indirect, casted,
   or otherwise ambiguous shapes abstain.

The resolver examines a bounded number of bare-call assignments and produces
at most one owner candidate. Multiple eligible wrappers, repeated target calls,
duplicate definitions, repeated relevant low-level calls, multiple returns, or
unresolved types are rejection states, never ranking heuristics.

## Materialization

For the proven caller assignment:

```c
header = mnDiagram_CreateFighterHeader(fighter_id, assets);
```

reuse the existing owner split:

```c
HSD_JObj* window_order_synthetic_header;
...
window_order_synthetic_header =
    mnDiagram_CreateFighterHeader(fighter_id, assets);
header = window_order_synthetic_header;
```

Exactly one candidate is emitted for the chain. This is both the owner split
and the caller-side alias boundary needed by the search; no helper-body rewrite
or downstream-use rewrite is required. Emitting a second alias form would add
an independent source transformation without stronger attribution proof.

The probe keeps the existing
`window-order-call-return-source-order` provenance kind and adds:

- `resolution=inline-wrapper-return-owner`;
- the wrapper name and source span;
- the low-level call symbol and span;
- the helper result local, return span, and normalized pointer type;
- the visible owner and assignment span;
- the exact attributed copy chain;
- `candidate_limit=1`.

No source is emitted unless all fields are proven. The original attribution is
copied verbatim into probe provenance.

## Diagnostics and stop condition

Each unique attributed chain receives one top-level outcome in
`call_return_source_probe`:

- materialized, with its single probe label; or
- rejected, with one stable `rejection_reason`.

Concrete reasons distinguish invalid copy chain, missing/ambiguous target
assignment, missing/duplicate/non-inline helper definition, repeated relevant
call, unsupported call owner, missing/multiple/non-direct return, unresolved or
incompatible type, preprocessor/macro ambiguity, and unsafe source span. The
lead's `terminal_blocker` repeats the rejection reason so JSON and text
consumers do not need to interpret nested details.

The issue is complete when the retained chain either produces the bounded
source candidate and a compiled pcdump through the existing campaign or records
one of these exact rejection reasons. Generic
`call-return-owner-copy-not-found` is retained only for legacy direct-owner
shapes that never enter the wrapper resolver.

## Tests and verification

TDD fixtures cover the retained positive shape and these negative cases:

- two eligible wrappers;
- repeated low-level calls in one wrapper;
- multiple or non-direct returns;
- compound target RHS;
- unresolved or incompatible pointer type;
- invalid/missing copy-chain provenance;
- duplicate or macro/preprocessor-controlled helper definitions.

Focused window-order and select-order tests confirm the one-candidate bound
and exact provenance. The retained source replay completed in the fresh ignored
directory `build/select-order/issue1248-inline-owner-replay`: it produced the
single source variant
`probes/window-order-call-return-ig72-before-0.c`. The replayed target contains
one `window_order_synthetic_header` declaration and the exact caller split from
`mnDiagram_CreateFighterHeader(...)` to `header`, so the retained `[72, 86, 3]`
chain is source-actionable and bounded.

The compile/scoring portion stopped at two concrete environment-output
blockers. First, `build/GALE01/report.json` contains zero function records for
`mnDiagram_DrawFighterHeaders`, so the normal target lookup cannot establish
the comparison target. After one compiler setup attempt, branch-local
`score-source` wrote
`probes/window-order-call-return-ig72-before-0.pcdump.txt`, but that pcdump also
contains zero occurrences of `mnDiagram_DrawFighterHeaders` even though its
paired source contains the target. It therefore cannot supply a target pcdump
or structural-guard score. The source replay is complete; compiled retention
evidence remains blocked specifically by the missing target in both generated
artifacts, and this change does not repeat compiler setup.
