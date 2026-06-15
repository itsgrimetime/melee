# Source Transform Catalogue

This catalogues tooling that generates targeted C-source variants, separate
from the full decomp-permuter search space.  The machine-readable source of
truth is `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`; this
page is the human summary.

Headline inventory:

- 13 source-producing surfaces
- 168 counted techniques across those surfaces
- 115 concrete form summaries

The technique count is per surface, not globally deduplicated.  For example,
`debug select-order-search` reuses the `lifetime-layout` probe families, so
those families are counted under both surfaces.

## Summary Table

| Surface | Generator / implementation | Count basis | Count | Techniques |
| --- | --- | --- | ---: | --- |
| direct mutator functions | `src.mwcc_debug.mutators` | mutator functions | 3 | `type-change`, `insert-alias-before-use`, `preserve-lifetime-after-use` |
| `debug mutate decl-orders` | `src.cli.debug.mutate_decl_orders_cmd` | ordering strategies | 4 | `promote`, `demote`, `adjacent-swap`, `full-permutation` |
| `debug mutate lifetime-layout` | `src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes` | operator families | 19 | `frame-reservation-pad-stack`, `call-return-compare-chain`, `expression-shape`, `declaration-order`, `loop-counter-hoist`, `loop-counter-type`, `indexed-pointer-loop`, `pointer-walk-loop`, `pointer-base-call-loop`, `temp-introduction`, `temp-removal`, `type-width`, `declaration-use-distance`, `guard-shape`, `early-guard-return`, `block-scope`, `loop-init`, `condition-nesting`, `call-argument-tempization` |
| `debug mutate control-flow-shape-search` | `src.mwcc_debug.control_flow_shape.generate_control_flow_shape_probes` | operator families | 12 | `early-guard-return`, `condition-nesting`, `loop-init`, `loop-counter-type`, `guard-shape`, `call-return-compare-chain`, `pointer-walk-loop`, `pointer-base-call-loop`, `ternary-to-if-else`, `if-else-to-ternary`, `bool-condition-spelling`, `if-equality-to-single-case-switch` |
| `debug mutate indexed-struct-search` | `src.mwcc_debug.pressure_explorer.generate_indexed_struct_pointer_probes` | operator families | 1 | `indexed-struct-pointer` |
| `debug mutate name-magic-source-declarations` | `src.mwcc_debug.name_magic_source.generate_name_magic_source_probes` | operator families | 4 | `data-symbol-static-to-global`, `bss-anchor-source-binding`, `sdata2-named-float-load`, `name-magic-source-combined` |
| `debug mutate frame-transform-search` | `src.mwcc_debug.pressure_explorer.generate_frame_directed_probes` | operator families | 5 | `frame-reservation-pad-stack`, `frame-local-dematerialize`, `frame-direct-literal-at-final-fp-call`, `frame-split-fp-const-lifetime`, `frame-magic-scratch-relocation` |
| `debug mutate simplify-order` | `src.mwcc_debug.simplify_variants` | variant-source adapters | 5 | `decl-orders-source`, `insert-alias-source`, `holder-lifetime-source`, `type-change-source`, optional `permuter-source` |
| `debug mutate search` | `src.mwcc_debug.tier3_search.plan_seeds` | seed mutator kinds | 3 | `insert-alias`, `type-change`, `source-shape` |
| `debug select-order-search` | `src.cli.debug.debug_select_order_search_cmd` | reused `lifetime-layout` operators | 19 | same 19 operators as `debug mutate lifetime-layout` |
| `debug search structure` | `src.search.structure` | axis-specific operators | 49 | decl-order, control-flow, case-order, statement-order, source-lifetime, inline-boundary, and loop-shape-expanded operators |
| `debug search plan-transforms` / directed | `src.search.directed.transform_corpus` | transform families | 40 | `temp_sink_hoist`, `condition_split_merge`, `scoped_alias`, `declaration_use_boundary`, `coloring_register_steering`, `ranked_cursor_iv_unification`, `loop_index_pointer_walk_split`, `helper_shape`, `counter_type_shape`, `reload_branch_scope`, `lifetime_preserve_shorten`, `same_type_local_lifetime_reuse`, `independent_statement_order`, `data_table_indirection_shape`, `explicit_zero_return`, `named_zero_local_shape`, `raw_index_struct_field_shape`, `bool_int_accumulator_shape`, `global_float_literal_shape`, `fp_subtraction_operand_reassociation`, `abs_macro_expression_fold`, `callback_cast_elision`, `zero_compare_logical_not`, `function_codegen_pragma_shape`, `redundant_pointer_cast_elision`, `unused_trailing_parameter`, `outgoing_parameter_area_shape`, `vector_alias_type_shape`, `minmax_macro_ternary_shape`, `assert_macro_expansion_shape`, `assignment_expression_temp_seed`, `string_literal_data_blob_field_shape`, `raw_pointer_offset_struct_field_shape`, `comma_operator_noop_expression_shape`, `numeric_cast_shape`, `void_to_value_return_shape`, `global_pointer_alias_shape`, `empty_do_while_barrier`, `scheduler_order_source_realizer`, `switch_case_order_default_shape` |
| `debug inspect stack-homes --compile-local-array-variants` | `src.mwcc_debug.stack_home_explorer.generate_local_array_sqrt_variants` | fixed local-array `sqrtf` variants | 4 | `local-array-sqrt-slot-1-index-0`, `local-array-sqrt-slot-2-index-1`, `branch-local-array-sqrt-slot-1-index-0`, `branch-local-array-sqrt-slot-2-index-1` |

## Larger Buckets

`debug mutate lifetime-layout` has the broadest lower-level corpus.  Several
operators are umbrella families:

- `call-return-compare-chain`: switch, inverted chain, copy-in-else, split-direct, narrow-pointer.
- `expression-shape`: assignment-expression CSE removal, dx/dy temps, abs discriminator split.
- `indexed-pointer-loop`: bound local, index temp, base alias, address temp.
- `pointer-walk-loop`: index temp, base alias, address temp, value temp, induction pointer, end pointer.
- `pointer-base-call-loop`: indexed call, value temp, address temp, induction pointer, end pointer.

`debug search structure` is the broadest high-level search surface.  Its 49
axis-specific operators break down as:

- decl-order: 3
- control-flow: 12
- case-order: 3
- statement-order: 4
- source-lifetime: 14
- inline-boundary: 8
- loop-shape-expanded: 5

`debug search plan-transforms` is the current proof-vector-directed corpus.
It has 40 transform families backed by 62 mutator keys.  `explicit_zero_return`
is backed by the narrow `add_explicit_zero_return` mutator for one-call wrapper
bodies.  `helper_shape` now has guarded scalar helper inline/extract probes for
single-expression static helpers and repeated assignment RHS expressions.
`named_zero_local_shape` introduces source-visible typed NULL sentinel locals
for paired pointer `!= NULL` checks and `= NULL` resets, changing reset-side
zero-CSE web membership without changing the tested or stored value.
`coloring_register_steering` now emits guarded declaration-window rotation,
declaration demotion, dead-counter reuse, reused-loop-counter split,
byte-local widening probes, and FPR product-dependent recompute probes, then
aliases guarded declaration-order, initializer-split, loop-counter,
counter-width, and same-type lifetime edits as register-coloring probes for
mndiagram force-phys residuals.
`same_type_local_lifetime_reuse` now has guarded local-declaration reuse probes
for same-type locals with proven non-overlapping lifetimes.
`ranked_cursor_iv_unification` has exact ranked selection-loop probes that
replace an indexed max-value read with the cursor value accumulator while
preserving sentinel behavior, plus a rank-pointer tail return probe.
`function_codegen_pragma_shape` now has exact guarded
`#pragma push` / `#pragma dont_inline on` / `#pragma pop` add/remove probes
for focused functions.
`global_float_literal_shape` now has guarded source-local float literal/global
constant swap probes for unique target-width constant values.
`fp_subtraction_operand_reassociation` now has exact subexpression probes for
true `-X - C` floating literal subtractions, rewriting them as `-C - X`.
`callback_cast_elision`, `redundant_pointer_cast_elision`, and
`vector_alias_type_shape` now have guarded local type-compatibility probes for
call-argument callback casts, pointer call/assignment casts, and local
declaration alias spelling.
`unused_trailing_parameter` now has guarded static full-unit probes that add or
remove one trailing unused formal while updating locally visible prototypes and
direct call sites together.  `outgoing_parameter_area_shape`
now has exact high-arity call-site probes that materialize selected arguments
as locals or dematerialize immediate one-use argument locals back into calls, so
`frame-transform-search` can score outgoing parameter-area word-count changes.
`independent_statement_order` now has guarded adjacent same-block assignment
swaps with local read/write dependency proof.  `data_table_indirection_shape`
now has guarded source-local immutable pointer-table read probes, and
`raw_index_struct_field_shape` now has guarded typed pointer-parameter raw
indexed byte-offset field probes.  The scalar expression families now have
guarded forms for bool/BOOL OR-accumulator integer spelling,
single-evaluation zero-compare spelling, simple ABS ternary folds, and simple
MIN/MAX macro-to-ternary expansion.  The later mined families now have
conservative guarded forms: assert collapse to `HSD_ASSERTMSG`, adjacent
assignment-expression seed folding, unique string-data field substitution,
source-local raw pointer offset to struct field rewriting, no-op comma RHS
wrapping, same-formal-type numeric cast elision, static void tail-call return
forwarding, source-local global pointer aliasing, empty do/while barrier
insertion, and adjacent break-terminated switch arm swapping.

The 2026-06-13 mining sweep of job `88baa039` (commit range
`af6f07f43..upstream/master`) added ten more record-only families promoted from
repeated, consolidated source transitions: `assert_macro_expansion_shape`,
`assignment_expression_temp_seed`, `string_literal_data_blob_field_shape`,
`raw_pointer_offset_struct_field_shape`, `comma_operator_noop_expression_shape`,
`numeric_cast_shape`, `void_to_value_return_shape`, `global_pointer_alias_shape`,
`empty_do_while_barrier`, and `switch_case_order_default_shape`.  These now
have initial guarded mutators for narrow source-local proof cases.  See the
mining ledger plan
(`docs/superpowers/plans/2026-06-13-transform-corpus-mining-ledger.md`) for the
full candidate consolidation map and the ledger-only buckets (PAD_STACK /
stack-padding, non-loop integer-width, single-use temp-inline, and the
unrepeated singleton tail) that were deliberately not promoted.

## Command Availability

Transform-corpus probes can be planned directly, consumed by directed search, or
appended to source-shape scoring commands.  The scoring commands keep their
existing defaults; corpus probes are appended only when `--include-transform-corpus`
or `--transform-family` opts in.

Plan and inspect the bounded source-shape corpus:

```bash
melee-agent debug search plan-transforms \
  -f fn_80000000 -u melee/example/file \
  --force-phys 0:58:4 \
  --source-file src/melee/example/file.c \
  --max-per-family 3 --json
```

Use the corpus through directed search proposals:

```bash
melee-agent debug search directed \
  -f fn_80000000 -u melee/example/file \
  --seed src/melee/example/file.c \
  --directed-force-phys 0:58:4

melee-agent debug search run \
  -f fn_80000000 -u melee/example/file \
  --seed src/melee/example/file.c \
  --directed-force-phys 0:58:4
```

Append transform-corpus probes to lifetime, coalesce, and select-order scoring:

```bash
melee-agent debug mutate lifetime-layout \
  -f fn_80000000 --pcdump pcdump.txt \
  --source-file src/melee/example/file.c \
  --include-transform-corpus \
  --transform-family comma_operator_noop_expression_shape --json

melee-agent debug coalesce-search \
  -f fn_80000000 --target r37=r40 \
  --pcdump pcdump.txt --source-file src/melee/example/file.c \
  --include-transform-corpus \
  --transform-family comma_operator_noop_expression_shape --json

melee-agent debug select-order-search \
  -f fn_80000000 --target r32\<r33 \
  --pcdump pcdump.txt --source-file src/melee/example/file.c \
  --include-transform-corpus \
  --transform-family comma_operator_noop_expression_shape --json
```

Frame-transform search uses the same opt-in flags.  With
`--include-transform-corpus` and no explicit family filter, it defaults to the
frame-relevant mined families such as assignment-expression seeds, string/data
field shape, raw pointer offset field shape, no-op comma expressions, numeric
casts, void tail-call return forwarding, global pointer aliases, and empty
do/while barriers.

```bash
melee-agent debug mutate frame-transform-search \
  -f fn_80000000 --pcdump pcdump.txt \
  --source-file src/melee/example/file.c \
  --include-transform-corpus --json
```

Known example: `it_802BCB88` in PR #2674.  Scratch `3pVIE` could be matched by
removing an inline helper and hoisting a loop counter, but the reviewed source
kept the helper and reused `cur` for the later `prev` phase:

```c
ItemLink* cur;
ItemLink* prev;

cur = link->next;
/* use cur for next-link logic */

prev = it_802BCB88_prev(link);
if (prev != NULL) {
    pos1 = prev->pos;
}
```

```c
ItemLink* cur;

cur = link->next;
/* use cur for next-link logic */

cur = it_802BCB88_prev(link);
if (cur != NULL) {
    pos1 = cur->pos;
}
```

The candidate mutator should be dominance/lifetime-aware: when same-type locals
have non-overlapping live ranges, try replacing the later local with the earlier
one and deleting the later declaration.  Pointer temps named like `cur`, `prev`,
`next`, and `iter` are useful hints, but not sufficient by themselves.

Known example for `independent_statement_order`: a mined source transition
reordered two adjacent global stores after a call:

```c
lbAudioAx_80023F28(un_804D6DB8);
un_804D6DC0 = 0;
un_804D585C = un_804D6DB8;
```

```c
lbAudioAx_80023F28(un_804D6DB8);
un_804D585C = un_804D6DB8;
un_804D6DC0 = 0;
```

The guarded mutator added for this family only covers adjacent local scalar
assignments with complete read/write proof.  This broader global-store form
still needs dependency and alias checks before it gets a mutator.

Known example for `data_table_indirection_shape`: a mined source transition
changed a global table access from direct dynamic indexing to a typed outer
table indirection:

```c
lbAudioAx_80023B24(un_804D6DA8[un_804D6DB4]);
```

```c
lbAudioAx_80023B24(((int**) un_804D6DA8)[5][un_804D6DB4]);
```

This is high-risk and should only be generated when a table-layout signal is
available for the global/archive-backed data expression.

Known example for `explicit_zero_return`: a non-void side-effect wrapper gained
an explicit zero return:

```c
int un_803004B4(int arg0)
{
    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);
}
```

```c
int un_803004B4(int arg0)
{
    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);
    return 0;
}
```

This now has a concrete mutator for the narrow wrapper form: a body with one
plain side-effect call, no existing return, and no preprocessor lines.

Known example for `named_zero_local_shape`: menu-count cleanup code can name the
NULL sentinel used by both a check and reset, changing the zero value's local
web membership:

```c
if (labels[i] != NULL) {
    HSD_TextRemove(labels[i]);
    labels[i] = NULL;
}
```

```c
HSD_Text* labels_null = NULL;
if (labels[i] != NULL) {
    HSD_TextRemove(labels[i]);
    labels[i] = labels_null;
}
```

Known example for `raw_index_struct_field_shape`: raw indexed `user_data`
storage was rewritten through typed fields once a layout was known:

```c
int* user_data = gobj->user_data;
if ((u32) user_data[2] == (u32) arg0) {
    if (user_data[12] != -1 && user_data[12] == arg1) {
        AXDriverKeyOff(user_data[12]);
    }
}
```

```c
lbAudioAx_UserData* ud = gobj->user_data;
if (ud->entity == arg0) {
    if (ud->voice_id != -1 && ud->voice_id == arg1) {
        AXDriverKeyOff(ud->voice_id);
    }
}
```

Known example for `bool_int_accumulator_shape`: a predicate accumulator was
kept at integer width while preserving bitwise OR accumulation:

```c
bool test;
test = mpColl_800471F8(coll);
if (test != false) {
    ip->xC30 = coll->floor.index;
}
test |= it_80276308(gobj);
test |= it_802763E0(gobj);
return test;
```

Known example for `global_float_literal_shape`: `itDosei_UnkMotion1_Anim`
mining found named global float constants rewritten as literal constants inside
the same expression:

```c
it_804DC874 * expr + it_804DC870
```

```c
0.5F * expr + 1.0F
```

Known example for `abs_macro_expression_fold`: `itDosei_UnkMotion1_Phys`
mining found an absolute-value temp/branch shape collapsed to an `ABS(expr)`
style expression at the single use site:

```c
tmp = expr;
if (tmp < 0.0F) {
    tmp = -tmp;
}
use(tmp);
```

```c
use(ABS(expr));
```

Known example for `callback_cast_elision`: `itMaril_UnkMotion0_Coll` mining
found an explicit callback cast removed when the callee prototype already
accepted the callback type:

```c
it_8026B3A8(gobj, (void (*)(HSD_GObj*)) callback);
```

```c
it_8026B3A8(gobj, callback);
```

Known example for `zero_compare_logical_not`: `itLizardon_UnkMotion3_Anim`
mining found a helper-call zero comparison rewritten with logical-not spelling:

```c
if (call(gobj) == 0) {
    return false;
}
```

```c
if (!call(gobj)) {
    return false;
}
```

Known example for `function_codegen_pragma_shape`: repeated mining examples
added local codegen pragmas around otherwise unchanged tiny functions:

```c
bool itZrshell_UnkMotion4_Anim(HSD_GObj* gobj)
{
    return false;
}
```

```c
#pragma push
#pragma dont_inline on
bool itZrshell_UnkMotion4_Anim(HSD_GObj* gobj)
{
    return false;
}
#pragma pop
```

Known example for `redundant_pointer_cast_elision`: pointer call arguments lost
explicit casts once the local type/prototype carried the same information:

```c
Item_80268E5C((HSD_GObj*) gobj, arg1);
```

```c
Item_80268E5C(gobj, arg1);
```

Known example for `unused_trailing_parameter`: a function signature gained a
trailing formal that the body does not reference, exposing call-contract shape:

```c
void pl_8003FDA0(Player* player)
{
    player->x0 = 0;
}
```

```c
void pl_8003FDA0(Player* player, int unused)
{
    player->x0 = 0;
}
```

Known example for `vector_alias_type_shape`: repeated mining examples swapped
equivalent point/vector aliases while leaving field access unchanged:

```c
void Camera_80030BBC(void)
{
    Point3d pos;
    use(pos->x, pos->y, pos->z);
}
```

```c
void Camera_80030BBC(void)
{
    Vec3 pos;
    use(pos->x, pos->y, pos->z);
}
```

Known example for `minmax_macro_ternary_shape`: simple clamp macros were
rewritten as explicit conditional expressions:

```c
value = MAX(*ptr + amount, (u32) -1);
```

```c
value = ((*ptr + amount) > -1) ? -1 : (*ptr + amount);
```

```c
s32 test;
test = mpColl_800471F8(coll);
if (test != 0) {
    ip->xC30 = coll->floor.index;
}
test |= it_80276308(gobj);
test |= it_802763E0(gobj);
return test;
```

## Families promoted from the 2026-06-13 mining sweep

These ten record-only families were promoted from repeated, consolidated source
transitions mined from job `88baa039`.  Each is illustrated by a representative
mined instance.

Known example for `assert_macro_expansion_shape`: `grAnime_801C8780` mining
collapsed a hand-expanded assert back into the `HSD_ASSERT` macro form:

```c
if (archive == NULL)
    __assert("granime.c", 0x617, "0");
```

```c
HSD_ASSERT(0x617, archive);
```

Known example for `assignment_expression_temp_seed`: `mpLib_DrawSnapping`
mining folded a standalone seed store into an embedded assignment expression
(the chained `a = b = c` form is the sibling variant):

```c
item = HSD_GObj_Entities->items;
if (item != NULL) {
```

```c
if ((item = HSD_GObj_Entities->items) != NULL) {
```

Known example for `string_literal_data_blob_field_shape`: `grIceMt_801F71E8`
mining replaced inline `OSReport` string literals with named data-blob field
references holding the same bytes (the string analog of
`global_float_literal_shape`):

```c
OSReport("loaded stage %d\n", id);
```

```c
OSReport(grIm_803E4800.report_format, id);
```

Known example for `raw_pointer_offset_struct_field_shape`: `grRCruise_80201918`
mining rewrote a raw byte-offset pointer cast as a typed struct field (the
offset/cast sibling of the index-load family `raw_index_struct_field_shape`):

```c
*(Vec3*) ((u8*) gp + 0xE0) = scroll;
```

```c
gp->u.scroll.x1C = scroll;
```

Known example for `comma_operator_noop_expression_shape`: `it_802886C4` mining
introduced a no-op comma operand at an assignment:

```c
jobj = (HSD_JObj*) HSD_GObjGetHSDObj(gobj);
```

```c
jobj = (0, (HSD_JObj*) HSD_GObjGetHSDObj(gobj));
```

Known example for `numeric_cast_shape`: `it_802B4224` mining elided a redundant
numeric cast at a call argument (the family also covers cast *insertion* to
steer int/float conversion):

```c
it_8026F790(gobj, (f32) (M_PI_2 * (f64) facing_dir));
```

```c
it_8026F790(gobj, M_PI_2 * facing_dir);
```

Known example for `void_to_value_return_shape`: `fn_8017F1B8` mining widened a
void function to forward its tail call's result (distinct from
`explicit_zero_return`, which appends `return 0`):

```c
void fn_8017F1B8(Item* it) { ...; fn_8017F0A0(it); }
```

```c
s32 fn_8017F1B8(Item* it) { ...; return fn_8017F0A0(it); }
```

Known example for `global_pointer_alias_shape`: `fn_8017FE54` mining cached a
named global's base in a typed local pointer and routed member accesses through
it (distinct from `scoped_alias` and `data_table_indirection_shape`):

```c
lbl_80472D28.field = x;
use(lbl_80472D28.other);
```

```c
struct lbl_80472D28_t* state = &lbl_80472D28;
state->field = x;
use(state->other);
```

Known example for `empty_do_while_barrier`: mining found a no-op statement
barrier inserted between statements to perturb scheduling and register
allocation (`it_802BBD64` used the equivalent self-assignment form):

```c
process(cur);
update(cur);
```

```c
process(cur);
do {
} while (0);
update(cur);
```

Known example for `switch_case_order_default_shape`: `grBigBlue_801EDF44`
mining reordered independent switch arms (and `it_802D24A0` added an explicit
`default: break;`); identical bodies, behavior-preserving dispatch reshape:

```c
switch (kind) {
case 1: a(); break;
case 7: b(); break;
case 9: c(); break;
}
```

```c
switch (kind) {
case 1: a(); break;
case 9: c(); break;
case 7: b(); break;
}
```

## Maintenance

When adding a new targeted source transform, update
`source_transform_catalog.py` in the same change.  The drift tests in
`tools/melee-agent/tests/test_source_transform_catalog.py` check the catalogue
against the live control-flow operator tuple, source-lifetime tuples, directed
transform families, and directed mutator dispatch table.
