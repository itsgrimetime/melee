# Issue 974/975 Source-family Handoff Plan

## Scope

Fix two baseline-escape tooling gaps:

- #975: retained `.c` files for nested source-family discovery probes;
- #974: terminal evidence for the fully scored Sort source-family progress
  plateau.

## Implementation

1. Add regression coverage for retained source-family probe files under
   candidate-file generation.
2. Add regression coverage for the Sort source-family plateau and for a fresh
   top-level progress row that must remain actionable.
3. Extend nested source-family probes to carry range-scoped full source only
   during retained-file generation.
4. Refactor candidate retention to write both primary and nested candidates with
   stable bounded filenames and path metadata.
5. Add the source-family progress plateau classifier with compatibility-preserved
   terminal summary output.
6. Run focused tests, command smoke checks, refresh the editable install, resolve
   only #974 and #975.

## Verification

Primary regression command:

```bash
python -m pytest tools/melee-agent/tests/test_post_ceiling_baseline_escape.py
```

Smoke checks:

```bash
melee-agent debug search baseline-escape --help
melee-agent issues list
```
