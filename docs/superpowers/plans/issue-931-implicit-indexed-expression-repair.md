# Issue 931: retained implicit indexed-expression repair

## Context

Issue 931 follows issue 930. The retained SortNames target-live-range family now
generates address/value/coupled probes, but the matcher reported two gaps:

- fallback goals use `sorted_names[max_idx]` while retained source can spell the
  same address side as `sorted_names[(max_idx)]`;
- materialized element-pointer probes are not the preferred first-divergence
  source shape for this Case-C frontier. The next lane should keep the indexed
  address expression implicit and vary spelling/base/index source shape.

The referenced `$superpowers:brainstorming` path is not present on this machine,
so this plan is the local design artifact for the requested design cycle. An
independent Codex subagent is reviewing the same implementation surface.

## Existing Capability Check

`melee-agent capabilities search "Sort Case-C implicit indexed-expression repair"`
found adjacent diagnostic/suggestion commands, but no retained SortNames
source-probe lane that preserves implicit indexed address temps. The existing
`indexed_byte_address_temp_steering` transform family already has the closest
source vocabulary: same-line spelling, base aliases, condition index aliases,
and value/index temps.

## Design

Extend the existing `retained_gpr_case_c_target_live_range_repair` family rather
than adding a new family. It already carries protected/attempted target metadata,
validation classification, exact-stop behavior, and command-level summaries.

Implementation steps:

1. Normalize harmless index parentheses for retained repair expressions, so
   `sorted_names[max_idx]` and `sorted_names[(max_idx)]` match the same role.
2. Derive the address expression from the source when the default goal expression
   misses because of equivalent index spelling.
3. Add bounded implicit indexed-expression probes that keep the address temp
   compiler-created:
   - normalize/remove harmless `max_idx` parentheses;
   - introduce a scoped index alias used inside `sorted_names[...]`;
   - introduce a base alias used inside `base_alias[...]`.
4. Preserve the existing #930 materialized probes for compatibility, but mark
   implicit-expression probe kinds separately in metadata and summaries.
5. Update docs/catalog text and CLI exhaustion hints to name the implicit
   indexed-expression spelling lane.

## Tests First

- Planner unit test: a retained source fixture with `sorted_names[(max_idx)]`
  and default goal `sorted_names[max_idx]` must materialize address/coupled
  candidates plus implicit indexed-expression spelling candidates.
- CLI smoke: `plan-transforms` with the retained target-live-range family emits
  the new implicit probe kinds and summary next-lever classes.
- Validation summary smoke: protected-negative/lost-protected classification
  still works for the expanded family.

## Verification

Run the focused retained/window-order pytest set, `py_compile`, `git diff
--check`, an unscored `plan-transforms` smoke, and a scored SortNames smoke using
`debug target score-source` against the IG34/IG44 target spec.
