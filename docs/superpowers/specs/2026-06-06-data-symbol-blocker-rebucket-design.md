# data-symbol blocker rebucket design

Date: 2026-06-06
Status: Codex-reviewed; implementation may proceed
Issue: #459

## Problem

The function taxonomy marks every `data-symbol-or-relocation` residual as
`source_actionability=current-tools-data-symbol`. Harvest then repeatedly runs
`name-magic-source-declarations` on rows where that harness already has a stable
non-candidate blocker such as `no-name-magic-candidate`,
`ambiguous-sdata2-value`, or `sdata2-pool-order-dependent`.

This makes bounded data-symbol campaigns spend compile time on rows that are
known not to be source-candidate-ready.

## Goals

1. During taxonomy generation, run a cheap name-magic preflight for
   data-symbol rows without compiling generated probes.
2. Preserve preflight blocker, stop kind, probe count, and reason in taxonomy
   records and queues.
3. Keep `current-tools-data-symbol` only for rows where the harness can emit at
   least one source probe or has no stable non-candidate blocker.
4. Rebucket stable non-candidate rows to explicit blocker
   `source_actionability` values and physical subqueues.
5. Make harvest preview expose those blocker facets and avoid selecting the
   name-magic harness for rebucketed blocker rows.

## Non-goals

- Do not compile or score name-magic probes during taxonomy generation.
- Do not change the source candidate generator.
- Do not remove rows from the main `data-symbol-relocation.tsv`; rebucketing is
  additive and filterable.

## Design

Add an optional name-magic preflight runner to `classify_candidate()` and
`generate_inventory()`. The default runner invokes:

```text
melee-agent debug mutate name-magic-source-declarations -f <function> --source-file src/<file> --no-compile-probes --no-score-match-percent --json
```

For `data-symbol-relocation` records, attach:

- `name_magic_blocker`
- `name_magic_stop_kind`
- `name_magic_probe_count`
- `name_magic_reason`

If the blocker is one of `no-name-magic-candidate`,
`ambiguous-sdata2-value`, or `sdata2-pool-order-dependent` and
`name_magic_probe_count == 0`, change `source_actionability` to:

- `blocked-data-symbol-no-name-magic-candidate`
- `blocked-data-symbol-ambiguous-sdata2-value`
- `blocked-data-symbol-sdata2-pool-order-dependent`

The actionability reason should include the blocker and a no-source-lever
explanation. Rows with generated probes stay `current-tools-data-symbol` because
harvest can still emit scored candidates.

`generate_inventory()` should also write blocker subqueues named
`data-symbol-relocation.<blocker>.tsv`.

Harvest preview should facet `name_magic_blocker`. `select_harness()` should not
select `name-magic-source-declarations` for the new blocked
`source_actionability` values, even if `primary` remains
`data-symbol-or-relocation`. Explicit target-map harness overrides remain a
manual escape hatch for deliberate reruns; generated queues and default harness
selection must not treat rebucketed rows as executable current-tools work.

## Acceptance

- A data-symbol row with zero probes and blocker `no-name-magic-candidate` is
  written with `source_actionability=blocked-data-symbol-no-name-magic-candidate`.
- A data-symbol row with at least one generated probe stays
  `current-tools-data-symbol`.
- `ambiguous-sdata2-value` and `sdata2-pool-order-dependent` zero-probe rows are
  rebucketed to explicit blocked facets.
- `data-symbol-relocation.<blocker>.tsv` files are written for each blocker with
  matching rows.
- `harvest data-symbol-relocation --preview --where source_actionability=current-tools-data-symbol`
  shows only executable rows and exposes `name_magic_blocker` facets.
- Rebucketed blocker rows do not select or run the name-magic harness by
  default, including when harvested from the physical blocker subqueues.
