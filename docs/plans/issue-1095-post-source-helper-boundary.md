# Issue 1095: Draw Post-Source Helper-Boundary Terminal

## Root Cause

`tools/melee-agent/src/mwcc_debug/post_source_context_discovery.py::_draw_post_source_context_stage`
checked protected-expression reconcile before any helper-boundary terminal
stage. It also had no helper-boundary terminal final family for the Draw
coupled-FPR expression-lifetime path.

After issue #1093, retained-frontiers and allocator-ceiling correctly close
`draw-coupled-fpr-expression-lifetime-helper-boundary-handoff` and report
`draw-no-modeled-source-actionable-family-after-post-helper-boundary-expression-lifetime`.
However, `post-source-context-next-dimension` still selected older
`draw-protected-expression-subhunk-reconcile` terminal evidence when both
signals appeared in the artifacts.

## Fix Plan

- Add helper-boundary terminal constants and final family definitions to
  `post_source_context_discovery.py`.
- Extract helper-boundary terminal proofs from direct current-ceiling and
  retained-meta paths, analogous to protected-expression direct proof
  extraction.
- Check helper-boundary terminal evidence before protected-expression reconcile
  in `_draw_post_source_context_stage`.
- Emit `unsupported-source-family` with:
  - trigger/exhausted dimension:
    `draw-coupled-fpr-expression-lifetime-helper-boundary-handoff`
  - next family:
    `draw-no-modeled-source-actionable-family-after-post-helper-boundary-expression-lifetime`

## Regression Coverage

- Direct discovery fixture containing both stale protected-expression terminal
  evidence and newer helper-boundary terminal evidence.
- CLI-facing fixture that writes the post-source-context next-dimension payload
  and proves helper-boundary terminal evidence wins.

## Verification

Run:

```bash
python -m pytest tools/melee-agent/tests/test_post_source_context_discovery.py
```

Smoke the reporter artifacts through `debug search post-source-context-next-dimension`
with the #1095 retained-frontiers and allocator-ceiling JSON files.
