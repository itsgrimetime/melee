# Retained Source Bridge Follow-up Plan

## Goal

Close issues #794, #795, and #796 with targeted behavior changes in the existing
structure scoring and select-order diagnostics pipeline.

## Tasks

1. Add failing tests for retained full-TU structure scoring and executable-only
   inline-boundary drift anchors.
2. Add failing tests for source-bridge terminal next-lane metadata and
   `--campaign-dir` retention for single-probe select-order runs.
3. Update `tools/melee-agent/src/search/structure_scoring.py` so retained
   candidate sources are scored against the real TU resolved from `report.json`.
4. Update `tools/melee-agent/src/cli/debug/__init__.py` so inline-boundary drift
   payloads use executable source lines, single-probe generated sources honor
   `--campaign-dir`, and source-bridge summaries report terminal recombine/frame
   repair next-lane data.
5. Run targeted pytest files, py_compile for touched modules, CLI smoke checks,
   install editable `melee-agent` from `/Users/mike/code/melee`, resolve the
   issues, and commit only this work plus the spec/plan files.
