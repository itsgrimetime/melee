# Synthetic Owner-Split Realization Design

Date: 2026-06-19
Issue: #848

## Context

Select-order causal composition can now emit synthetic owner-split
`node_set_delta` payloads, but matcher-facing follow-up still stalls in two
places. `debug solve node-set-split` accepts synthetic owner-split requests as
introducible, yet it can report `no introduce-binding candidates generated` for
real mndiagram source. `debug search combine` also skips all pairs when two
owner-split candidates touch the same broad source hunk, even when the useful
edits are compatible local introductions.

The root cause found for the Sort artifact is offset handling. `source_spans`
returns UTF-8 byte ranges, while node-set-split slices Python strings with
those byte offsets. Non-ASCII documentation before the function shifts the
string offsets and prevents valid simple-local binding sites such as
`dst_iter = dst;` from being recognized.

## Approaches

The selected approach is a surgical repair of the existing realizer. Convert
span byte ranges to character ranges at the node-set-split binding boundary,
then add a guarded combine fallback for overlapping pure-introduction hunks.
This keeps current commands and scoring paths intact.

A broader alternative would make `source_spans` return character ranges
everywhere. That is higher risk because many tools intentionally persist byte
ranges from tree-sitter and compare them with other byte-based metadata.

A third alternative would add a new synthetic-owner-split scorer command. That
would duplicate `debug solve node-set-split` and `debug search combine` instead
of fixing the shared lanes that already own source materialization and scoring.

## Design

`tools/melee-agent/src/mwcc_debug/node_set_split.py` will reuse the existing
byte-to-character conversion pattern from `source_patch.py`. Binding-site
discovery and source rewriting will convert `StatementSpan.byte_range` and
`scope_byte_range` before indexing into source text. The public request shape
does not change. Synthetic owner-split requests still require a safe expression
and safe binding type, and unsafe expressions such as calls, increments, comma
expressions, or assignment forms remain rejected.

For an introducible request whose expression is already a visible simple local,
the generated source remains a normal local introduction: declare a unique
`<expr>_bind_<ig>_<site>` local, assign it from the expression at a valid plain
statement site, rewrite that occurrence, and then run the existing split
families on the introduced binding.

`tools/melee-agent/src/search/cli/__init__.py` will keep the current
non-overlap merge as the default. When hunks overlap, it will attempt one
conservative fallback for local-introduction hunks. Overlapping zero-length
declaration inserts at the same base line are unioned in candidate order.
Overlapping replacement hunks that share the same base region and whose changed
replacement statement can be expressed as identifier substitutions over the
same base statement compose those substitutions into one replacement statement.
Declarations and simple binding assignments are unioned in candidate order. If
the edits remove different base text, introduce duplicate declarations, contain
conflicting substitutions, or touch non-introduction statements, the command
will still return `overlapping-source-hunks`.

## Error Handling

Byte-to-character conversion clamps out-of-range byte offsets to the string
start or end, matching the existing `source_patch.py` behavior. Failed span
parsing continues to produce no patches instead of raising.

The combine fallback is all-or-nothing for each overlapping group. Ambiguous
overlaps are skipped with the existing reason, so the feature cannot silently
splice incompatible source.

## Testing

Regression tests cover:

- a non-ASCII comment before a function where synthetic owner-split `dst`
  produces introduce-binding patches;
- a coupled request that combines an existing local with that synthetic
  owner-split in non-ASCII source;
- `debug search combine` merging two overlapping compatible introduction
  hunks and preserving score-command execution;
- `debug search combine` still skipping overlapping non-introduction hunks.

Command smoke checks will run the focused pytest files and a JSON CLI combine
invocation. If a full command against reporter artifacts is available in the
local checkout, it will be run with a bounded candidate budget to confirm the
blocked reason changes from `no introduce-binding candidates generated` to
generated/scored evidence.
