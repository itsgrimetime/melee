# Name-Magic Ambiguous Relocation Design

## Problem

`debug mutate name-magic-source-declarations` stops before generating source
candidates when `checkdiff --no-name-magic` reports more than one relocation-side
line at a diff offset. For `mnDiagram_80242C0C`, this leaves the command at
`probe_count=0` with blocker `ambiguous-relocation-pair`, even though the diff
still contains source-addressable data-symbol evidence such as
`mnDiagram_804A0750` versus `...bss.0`.

The failure mode is too coarse: one ambiguous relocation offset discards all
earlier compatible relocation pairs and prevents agents from seeing whether any
safe source declaration candidate moves the score.

## Goals

- Preserve compatible relocation pairs found before or inside ambiguous offsets.
- Expand same-offset ambiguous relocation groups into bounded compatible
  alternatives instead of returning zero evidence immediately.
- Emit a source candidate for named BSS anchor pairs when a matching file-scope
  declaration or definition exists, including non-static BSS definitions such as
  `mnDiagram_804A0750`. This candidate keeps the source unchanged but binds the
  relocation to the declaration and lets the existing scoring path report the
  candidate's match score.
- Keep unsupported relocation kinds and missing source sites explicit through
  existing blockers.
- Keep candidate scoring safe: generated probes remain temporary files, and
  `--score-match-percent` continues to restore the real source tree after each
  candidate.

## Non-Goals

- Do not claim that BSS section-anchor ceilings are source-fixable.
- Do not rewrite real project source declarations for `mnDiagram_80242C0C`.
- Do not infer field paths for section-anchor offsets such as `...data.0+4`.
- Do not change `tools/checkdiff.py` normalization or name-magic renaming.

## Selected Approach

Extend `parse_name_magic_relocation_evidence` so ambiguity is no longer an
all-or-nothing result. The parser will still report
`NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR` when an offset cannot be uniquely
paired, but it will also retain any compatible alternatives that can be formed
from named expected symbols and supported current symbols with matching
relocation kinds.

Then extend `generate_name_magic_source_probes` so an ambiguous blocker with
retained relocations can still generate and score probes. BSS anchor relocations
will produce a `bss-anchor-source-binding` probe when the expected symbol has a
safe top-level source declaration or definition. This probe has no source edit; its value is
the retained provenance and the normal checkdiff score attached to the variant.
If materialized candidates do not validate as edit-bearing source fixes, the
command remains unvalidated instead of blocked at zero probes.

The CLI must also allow partial ambiguous evidence through its generation gate.
Today `mutate_name_magic_source_declarations_cmd` only calls the generator when
`parsed.blocker is None`; after this change it must also call the generator when
`parsed.blocker == AMBIGUOUS_RELOCATION_PAIR` and retained relocations are
present.

## Alternatives Considered

1. Use only `classification.bss_anchor_relocations` from checkdiff.
   This is simple, but it misses raw relocation alternatives that the parser can
   already see and does not help repeated ambiguous same-offset cases outside
   BSS anchors.

2. Pair relocations by nearest offset across the whole diff.
   This may catch line-shifted HA/LO pairs, but it risks inventing incorrect
   pairs when unrelated relocations are dense. The first implementation should
   only expand exact same-offset alternatives and preserve unambiguous earlier
   pairs.

3. Treat BSS anchor bindings as validated source fixes.
   This is misleading. A no-edit source-binding probe must be scored like every
   other candidate and is only evidence; it is not proof that the ceiling is
   source-fixable.

## Data Model

`NameMagicEvidence` keeps its existing `relocations`, `residual_diff_count`,
`blocker`, and `reason` fields. The meaning changes slightly: `relocations` may
be non-empty when `blocker` is `AMBIGUOUS_RELOCATION_PAIR`. Callers should treat
that as "usable partial evidence with unresolved ambiguity," not as a fully
resolved relocation set.

Ambiguous same-offset expansion is deterministic and bounded before probe
materialization:

- Sort offsets lexicographically, preserving the existing parser ordering.
- Within an offset, consider expected lines and current lines in diff order.
- Pair only entries with matching relocation kinds.
- Deduplicate by `(offset, kind, expected_symbol, current_symbol)`.
- Stop collecting ambiguous alternatives once `max_probes` compatible
  relocations have been retained for that generator invocation. Unambiguous
  relocations outside ambiguous groups still participate normally.

`NameMagicSourceProbe.operator` gains one value:

- `bss-anchor-source-binding`: no-op source candidate showing that a named BSS
  relocation maps to an existing file-scope declaration or definition.

The probe provenance includes the relocation offset, kind, expected symbol,
current symbol, and declaration span offsets in the source text.

## Safety Rules

- Ambiguous expansion only pairs relocation lines whose kinds match.
- Expected symbols must be named source symbols, not anonymous or section-anchor
  symbols.
- Current symbols must pass the existing supported-symbol predicate.
- Section-anchor offset expressions such as `...data.0+4` remain unsupported.
- BSS binding probes require a single top-level declaration of the expected
  symbol outside preprocessor regions, without top-level comma declarators or
  function prototypes.
- `bss-anchor-source-binding` variants are excluded from validated source-fix
  decisions and section-anchor source-fixable verdicts. A no-edit binding can
  rank and report score evidence, but only an edit-bearing candidate may mark the
  command as validated or source-fixable.
- Existing generated-source and real-tree restore behavior is reused unchanged.

## Testing

- Parser regression: same-offset ambiguity retains compatible alternatives while
  keeping blocker `AMBIGUOUS_RELOCATION_PAIR`.
- Generator regression: an ambiguous BSS anchor pair with a top-level
  declaration emits `bss-anchor-source-binding` instead of zero probes.
- Generator regression: BSS binding rejects function-local declarations,
  prototypes, preprocessor regions, and multi-declarators.
- CLI regression: mocked `name-magic-source-declarations` emits a generated BSS
  binding probe and scores it through the existing whole-source candidate path.
- Smoke check: live `mnDiagram_80242C0C` command no longer stops at
  `probe_count=0` for the ambiguous relocation-pair case.
