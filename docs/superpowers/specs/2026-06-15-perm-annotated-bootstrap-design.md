# PERM-Annotated Bootstrap Design

## Goal

Issue #731 reports that agents can create a decomp-permuter directory from the
repo source, but there is no obvious robust path to seed that directory from a
source file already annotated with `PERM_LINESWAP` or `PERM_GENERAL`. Hand-editing
those macros into `base.c` after import can leave candidates that still contain
raw `PERM_*` tokens and score as compiler failures.

The goal is to make `melee-agent debug permute bootstrap` the supported guided
PERM setup path: pass an annotated source file through import.py, preserve enough
metadata to prove that happened, and reject unsafe or stale annotated inputs.

## Approaches Considered

1. Teach bootstrap to synthesize `PERM_*` annotations itself. This is not
   selected because issue #731 is about importing agent-authored guided PERM
   source, and automatically generating correct PERM regions is a larger search
   problem.
2. Add a new command beside `debug permute bootstrap`. This is not selected
   because the capability index already exposes bootstrap as the import/setup
   entry point, and splitting the workflow would leave two partial bootstrappers.
3. Extend the existing bootstrap source-file path with an explicit annotated
   alias, PERM-aware defaults, safety validation, and verification metadata.
   This is selected because it is scoped, testable, and keeps all permuter setup
   repairs in one code path.

## Selected Design

`debug permute bootstrap` continues to call upstream decomp-permuter `import.py`,
then performs existing post-import repairs for same-TU inline callees, assertion
macro cleanup, compile script repair, and settings generation. The source-file
option gains an explicit alias:

```bash
melee-agent debug permute bootstrap \
  -f mnDiagram_SortNamesByKOs \
  --annotated-source-file /tmp/mnDiagram_SortNamesByKOs.perm.c
```

`--annotated-source-file` and `--source-file` are the same underlying option.
The new name documents the intended PERM-guided use without breaking existing
scripts. When the provided file differs from the repo TU, bootstrap temporarily
stages it over the real TU so import.py still discovers the correct Melee build
flags. That staging is protected by a repo-local lock so concurrent bootstrap,
build, or checkdiff work is not allowed to observe a half-restored source file
through this tool path.

Before staging, bootstrap validates that the annotated source file contains the
requested function. This catches stale notes or wrong-function experiments before
the real TU is touched. The validation reuses the existing source function finder
rather than regexing free-form text.

The default preserve regex expands from stack-padding helpers only to include
decomp-permuter PERM syntax:

```text
PAD_STACK|FORCE_PAD_STACK(?:_[0-9]+)?|PERM_.*
```

This does not synthesize PERM macros; it ensures import.py is invoked with a
PERM-aware preservation policy when annotated sources also contain macro
definitions or helper wrappers that match the `PERM_*` family.

## Metadata And Output

JSON output adds fields that make the path auditable:

- `preserve_macros`: the effective regex passed to import.py,
- `source_contains_perm_macros`: whether the requested source text contained
  `PERM_*`,
- `base_contains_perm_macros`: whether imported `base.c` still contains PERM
  syntax for the permuter parser,
- `base_object_status`: `present`, `absent`, or `invalidated-after-base-patch`.

Text output prints the effective preserve regex and source/base PERM status. It
also prints whether `base.o` is present, absent because import.py skipped a
PERM-containing base compile, or removed because bootstrap patched `base.c`.

## Error Handling

If `--source-file` or `--annotated-source-file` does not exist, the existing
Typer bad-parameter path remains. If it exists but does not contain the requested
function, bootstrap exits with code 2 and does not stage the file.

If post-import repairs edit `base.c`, bootstrap removes stale `base.o` and
reports `base_object_status=invalidated-after-base-patch`. If import.py did not
produce `base.o` because the annotated source contained PERM macros, bootstrap
reports `base_object_status=absent` without treating that as failure.

## Testing

Regression tests cover:

- default preserve regex includes `PERM_.*`,
- the new `--annotated-source-file` alias stages an annotated source and restores
  the repo TU,
- wrong-function annotated sources are rejected before staging,
- JSON/text metadata reports source/base PERM status and base object status,
- post-import patching does not append new raw PERM text after import.py returns.

The command-level closure smoke for #731 must run against
`mnDiagram_SortNamesByKOs`: bootstrap from a PERM-annotated source, run a bounded
permuter debug/candidate generation path, and verify the base score is the known
baseline around 80 with at least one generated candidate compiling without raw
`PERM_LINESWAP` or `PERM_GENERAL` compiler errors.

## Independent Review Notes

An independent Codex reviewer flagged four requirements that are included in
this design: lock the staging path, expose the effective preserve regex, validate
the annotated source contains the target function, and treat live candidate
generation as required closure evidence rather than relying only on unit tests.
