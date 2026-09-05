# Issue 1145: FPR Field-Load Owner Repair

## Target

- Issue: `#1145`
- Function: `mnDiagram3_8024714C`
- Root cause: pcode-only FPR `lfs` first-defs carried base virtual and offset data, but the window-order source bridge could not map those loads back to visible source when the pcode base virtual had no source owner. The field resolver also missed `Vec3` from `extern/dolphin/include` and could choose false nested field paths outside a field's byte range.

## Implemented Mechanism

- Parse FPR `lfs`/`lfd` first-def operands into `base_virtual` and `field_offset`.
- Resolve nested field offsets through bounded scalar typedef structs, including compact `f32 x, y, z;` anonymous typedefs from `dolphin/mtx.h`.
- Add `extern/dolphin/include` to source field include discovery.
- When a pcode FPR field-load base has no source owner, scan same-offset locals and inline accessors whose body returns the resolved field path.
- Materialize field-load owner probes by rewriting the containing statement, so multi-line expressions and call arguments produce compileable retained C.

## Acceptance Run

Command:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug select-order-search \
  -f mnDiagram3_8024714C \
  --target 'f41<f33' \
  --class 1 \
  --force-phys 41:30,39:30,38:30 \
  --max-probes 4 \
  --campaign-dir build/diagnostics/issue1145-select-order \
  --json > build/diagnostics/issue1145-select-order.json
```

Result:

- `listed_source_probes`: 3 field-load source probes.
- Generated source shape: materialize `HSD_JObjGetTranslationY(row0)` as `f32 window_order_row0_translate_y_probe` before the containing statement.
- Retained pcdump/source paths: `build/diagnostics/issue1145-select-order/probes/window-order-field-load-ig39-before-inline-accessor-{0,1,2}.c`.
- Best retained field-load candidate: `window-order-field-load-ig39-before-inline-accessor-0`.
- Target score: `0/3`; IG38 and IG39 remained `f31` instead of `f30`, IG41 was not present in the compiled candidate allocator facts.
- Classification: terminal proof/no-source-candidate improvement for this bounded family, with `terminal_exhaustion_summary.kind = degree-zero-fpr-case-c-source-exhaustion` and `terminal_blocker = support-order-targets-already-satisfied`.

Matcher handoff:

- Ledger classification: `revert candidate`.
- Do not retain the generated field-load temps as a keeper for #1145; they compile and prove the source family but do not improve the force-phys targets.
- Next source-level handoff: investigate why the active retained source produces current pcode loads at `lfs f39,60(r44)`, `lfs f38,56(r51)`, and `lfs f41,60(r68)` rather than the reporter's older `row0` owner set. The bounded `HSD_JObjGetTranslationY(row0)` temp family is exhausted for the current source.
