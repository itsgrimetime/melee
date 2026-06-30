# Source Lifetime And Downhill Hunk Repair Design

## Context

Issues #807 and #808 are both about source-search tools stopping before they
try source-actionable variants for `mnDiagram_SortNamesByKOs`.

#807 is a source-lifetime blocker: repeated `GetNameText` calls are rejected as
`callee-not-read-only`, even though the surrounding tooling already treats
`GetNameText` as a known helper for inline-boundary source variants. #808 is a
guard-repair blocker: a downhill source candidate can preserve protected
force-phys hits, but guard repair only adds new generic probes and never tries
subtracting the exact source hunks that created the downhill candidate.

## Design

Source-lifetime probing will carry explicit read-only helper metadata. The
default metadata includes the existing `fn_803AC634` helper and `GetNameText`
with return type `char*`. Callers can also pass read-only helper overrides, and
`debug search structure` exposes this as repeatable `--pure-helper NAME` or
`--pure-helper NAME=TYPE`. Generated variants keep the existing conservative
argument and mutation checks, but external helpers in the metadata can pass the
read-only gate and use the configured return type for the materialized temp.

Select-order guard repair will add a bounded subtractive probe family only in
the guard-repair lane. For each repair seed, it compares the original source
text against the downhill seed source, reverts one changed hunk at a time, and
adds small declaration type variants (`u8`/`int`) inside changed hunks. These
probes are scored by the existing select-order scoring path, so protected
register preservation, structural guard state, normalized diff lines, frame
delta, match percent, and lost/protected register accounting remain reported by
the current variant and guard-repair summaries.

## Stop Conditions

For #807, source-lifetime search must either produce scored candidate variants
for known/overridden pure helpers or report the same conservative blockers for
helpers that are not known read-only. For #808, guard repair must record and
score individual hunk-subtraction/type-variant probes, or report exhaustion via
the existing guard-repair ledger when no scored candidate preserves protected
hits while improving the structural guard.

## Testing

Unit tests cover `GetNameText` as default source-lifetime helper metadata,
explicit pure-helper overrides, CLI pass-through of `--pure-helper`, and
subtractive guard-repair probe generation. A CLI-level select-order regression
uses synthetic pcdumps and monkeypatched scoring to prove the guard-repair
campaign records and scores a source-hunk subtractive candidate.
