# Case C Source Probes Design

## Context

Issues #769 and #770 are follow-ups to the directed search work for
`mnDiagram_DrawCellNumber` and `mnDiagram_SortNamesByKOs`. Earlier product,
use-site, indexed-byte, and direct-global probes now enumerate local-expression
variants, but fresh first-divergence reports still classify the blockers as
allocator simplify-order problems:

- #769: class 1, IG39, Case C, unbound FPR temp sourced from the `y_offset`
  load/subtract area near `HSD_JObjGetTranslationY(jobj2)` and `base`.
- #770: class 0, IG44, Case C, unbound implicit GPR address temp with first def
  `add r44,r51,r34`, with a source bridge toward `dst_iter` / indexed-byte
  address expressions.

The existing capabilities search showed relevant commands already exist:
`debug inspect first-divergence`, `debug mutate simplify-order`, and
`debug select-order-search`. The missing piece is reusable source-transform
coverage in the transform corpus, not another CLI.

## Approaches Considered

### Recommended: Extend Existing Transform Families

Add the new probes to the families that already own the affected source shapes:
`coloring_register_steering` for #769 and `indexed_byte_address_temp_steering`
for #770. This keeps ranking, budgets, registry metadata, and mutator dispatch
aligned with existing directed-search behavior. It also lets tests reuse the
existing mnDiagram fixtures.

### Alternative: Add A New Generic First-Divergence Family

Create a `simplify_order_source_steering` family that consumes first-divergence
payloads. This is attractive long-term, but it requires a new payload contract
and more orchestration work before it can safely rank candidates. It would be
larger than these two filed issues require.

### Alternative: Rely On `debug mutate simplify-order`

Keep the transform corpus unchanged and ask match agents to run the dedicated
mutation command manually. This does not satisfy the queue request because
`debug select-order-search` would still fail to emit ranked, reproducible source
probes for the reported functions.

## Design

### #769 FPR Case C Probes

Extend `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`.
The detector should target FPR locals used as operands in downstream FPR product
assignments, especially the `y_offset` operand feeding `row_offset`. It must
support both source shapes observed in active worktrees:

```c
y_offset = HSD_JObjGetTranslationY(jobj2) - base;
```

and:

```c
y_offset = HSD_JObjGetTranslationY(jobj2);
y_offset -= base;
```

It will emit source variants that shift simplify-order position without moving
side-effecting calls across other statements:

- split a simple call operand into a named FPR temp immediately before the
  original assignment;
- split the complete adjusted RHS into a named FPR temp before assigning the
  target local;
- add an adjacent owner temp after the adjusted assignment and use that owner in
  the first downstream FPR product assignment.

The emitted anchors use a dedicated `steer_fpr_case_c_temp_order` mutator key
that performs only validated span replacement. The key must be listed in
`registry.py` and `_DIRECT_REGISTER_STEERING_KEYS` in `orchestrator.py`;
otherwise `generate_transform_probes` will not emit it.

Safety guards:

- accept only top-level simple assignments in the target function body;
- preserve the declaration type from the source (`f32`, `float`, or another FPR
  typedef) rather than hardcoding `float`;
- allow at most one simple call operand, and require the other adjusted operand
  to be a scalar local or numeric constant;
- reject increments, assignments, ternaries, comma expressions, indexed/member
  expressions, pointer dereferences, and duplicate ambiguous source spans.

### #770 Implicit Address Temp Case C Probes

Extend `tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`.
The detector should target the Sort source shape that keeps byte-array addresses
implicit, not materialized pointers:

```c
u8* dst = assets->sorted_names;
u32* tp = totals;
...
*dst_iter = (u8) n;
*tp = mnDiagram_SumNameKOs(n & 0xFF);
...
dst[i] = temp;
```

It will emit variants that shift the implicit base+index address temp while
preserving indexed-byte expression form:

- rewrite same-line final stores from `dst[i] = temp;` to a proven direct base
  such as `mnDiagram_804A076C.sorted_names[i] = temp;`;
- introduce a narrow index-local owner immediately before the same-line indexed
  store, for example `int sorted_names_store_idx_probe = i;` followed by
  `dst[sorted_names_store_idx_probe] = temp;`;
- convert the initialization pointer loop to an indexed store while keeping the
  address implicit, for example `dst[n] = (u8) n;`, while preserving the
  existing `tp` increment and `*tp = ...` totals write;
- emit same-line final-store probes before initialization-loop rewrites so
  small base/index spelling candidates are visible under low probe budgets.

Safety guards:

- prove alias-to-global relationships using existing direct-global helper logic;
- do not materialize `&array[index]` element pointers;
- do not emit broad pointer-walk rewrites;
- accept only simple one-line stores and simple loop headers with unique spans.

## Testing

Add regressions before production changes:

- `test_register_steering.py`: fixtures for both Draw `y_offset` shapes; assert
  the new FPR Case C strategies appear, target `y_offset`, preserve source type,
  and reject unsafe operands.
- `test_indexed_byte_address.py`: fixture for `mnDiagram_SortNamesByKOs`; assert
  the new implicit-address strategies appear and produce same-line indexed
  rewrites before loop-shape rewrites.
- `test_registry.py`: assert new mutator keys are listed in executable family
  metadata.
- `test_orchestrator.py`: assert `generate_transform_probes` emits
  `steer_fpr_case_c_temp_order` through the direct register-steering path.

Smoke verification must run from a clean/restored filed worktree source. Before
collecting evidence from `/Users/mike/.codex/worktrees/eeff/melee`, check its
`src/melee/mn/mndiagram.c` status and avoid using dirty generated probe
leftovers as the baseline.

## Completion Criteria

The issues can be resolved when the new probes are emitted by installed
`/opt/homebrew/bin/melee-agent`, compile successfully in targeted smokes, and
the issue notes include force-phys, opcode-shape, frame, and first-divergence
before/after evidence. If no candidate hits the target force assignment, the
resolution note must say that the requested source-probe class has been
exhausted and identify the remaining backend/register-allocation blocker.
