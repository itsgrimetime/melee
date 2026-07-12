# Final worktree-retirement fix report

## Scope

The final review findings were fixed without broadening retirement authority:

- successful `lsof` or `ps` queries with warning/permission text on stderr now
  fail closed as `process-query-failed`;
- post-removal registration verification canonicalizes paths without requiring
  unrelated registered worktree directories to still exist;
- ignored inventory uses incremental bounded capture with the 32 MiB and
  500,000-entry limits enforced while the child is running; and
- the approved design's trailing whitespace was removed.

## RED evidence

The focused regression selection was run before production changes:

```text
python -m pytest tools/melee-agent/tests/test_worktree_retirement.py -q \
  -k 'successful_query_warning or bounded_capture or unrelated_prunable_registration or late_ignored_inventory_overflow'

3 failed, 1 passed, 178 deselected
```

The three failures reproduced the review findings: stderr warnings were
discarded, ignored inventory still used unbounded `subprocess.run` capture,
and an unrelated prunable registration prevented the removed candidate from
being reported. The late-overflow partial-result test already passed because
the existing post-capture parser failed closed; the bounded-capture regression
is what exposed the missing early resource bound.

## GREEN evidence

After the implementation, the focused selection (including both `lsof` and
`ps` warning cases and the existing canonicalization-error guard) passed:

```text
6 passed, 177 deselected
```

The exact requested three-file suite passed:

```text
python -m pytest \
  tools/melee-agent/tests/test_worktree_retirement.py \
  tools/melee-agent/tests/test_worktree_doctor.py \
  tools/melee-agent/tests/test_worktree_artifacts.py -q

265 passed in 22.03s
```

Additional verification:

```text
python -m compileall -q tools/worktree_doctor \
  tools/melee-agent/tests/test_worktree_retirement.py
python -m ruff check tools/worktree_doctor/worktrees.py \
  tools/melee-agent/tests/test_worktree_retirement.py
git diff --check b583d8cd8...HEAD
```

All checks passed. The real linked-worktree regressions prove that a successful
candidate removal remains reported with its branch HEAD preserved when an
unrelated registration becomes missing/prunable, and that a later ignored
inventory overflow preserves the earlier removal in the partial result.
