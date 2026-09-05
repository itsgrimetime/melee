# Implementation Plan

1. Add generated pointer-walk initializer helpers in
   `tools/melee-agent/src/mwcc_debug/node_set_split.py`.
2. Wire those helpers into `generate_node_set_split_patches` before the generic
   read-site mutator families return `no-source-probes`.
3. Add `--force-phys` / `--transform-force-phys` parsing to
   `debug solve node-set-split` and attach force-phys target scores to candidate
   objectives.
4. Update coalesce-search continuation routes to pass the transform force-phys
   map through to node-set split.
5. Add focused regression tests in `test_node_set_split.py` and
   `test_coalesce_search.py`, then run the narrow test files and CLI smoke
   checks.
