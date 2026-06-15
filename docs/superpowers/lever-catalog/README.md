# Surrogate-solver lever catalog (D0, tracked)

This directory is the **tracked** lever catalog for the surrogate-as-solver
(`tools/melee-agent/src/search/solver/`). It is the spec §7 deliverable **D0**:
the curated lever entries are copied here, in-tree, so the shipped
`realize.py` reads tracked data at runtime rather than an out-of-tree agent
memory directory.

## File format

One JSON file per perturbation kind, consumed by
`src.search.solver.realize.load_catalog`:

- `node-add.json`
- `edge-add.json`
- `edge-remove.json`
- `order.json`

Each file is a JSON array of lever entries:

```json
[
  { "lever": "<lever-name>", "tier": "a" | "b" | "c", "note": "<free text>" }
]
```

`load_catalog(<this dir>)` returns a `{kind: [entries]}` dict. Lever priority
(spec §2 step 4) is node-set (`tier "a"`) > edge (`tier "b"`) > order
(`tier "c"`); within the node-set tier the order is
`alias > temp-for-expr > anchoring > per-loop-local > inline-base-cast`
(`realize.lever_priority_rank`). Entries are listed here in that priority order.

## Provenance

Promoted (T13 / spec §7 D0) from the Task-10 calibration snapshot
`tools/melee-agent/tests/fixtures/solver/calibration/catalog_snapshot/`. That
snapshot was originally curated from the campaign lever catalog recorded in the
agent-memory lever entries:

- `accessor_macro_inline_frame_lever`
- `comma_expr_defeats_licm_hoist`
- `mndiagram_levers_and_walls`
- `mndiagram_inputproc_simplify_tiebreak`
- `dispform_inline_base_cast_and_per_loop_locals`
- `call_shape_and_fmadds_operand_levers`

## CLI default

The `debug solve coloring` CLI's `--catalog-dir` parameter **defaults to this
directory**. Unit fixtures use inline catalogs (no dependency on this dir); the
pre-D0 §1.5 calibration spike read the agent memory-dir catalog via an explicit
`--catalog-dir`. With D0 landed, the shipped default reads tracked data here.
