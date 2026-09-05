# MWCC Inspector Candidate Include and Output Validation Design

## Goal

Make `tools/workflow/mwcc-inspect.sh` reliably inspect a staged candidate source: its transitive project headers must resolve on the remote host, and compiler diagnostics without structured IR must fail the command while preserving the captured output.

## Context

Candidate inspection runs MWCC with `-cwd source`. That makes relative include roots resolve from the temporary candidate source directory. The wrapper currently gives the staged candidate precedence only for `src` and `src/melee`; other relative project roots remain relative and can fail when a copied local header includes a project header. Separately, a zero inspector process exit is currently treated as success even when its output contains compiler errors or has no `FUNCTION:` section.

## Approaches Considered

1. Copy the entire source tree into the candidate directory. This would make every relative include root work, but it duplicates a large tree, risks stale copies, and masks the intended remote checkout context.
2. Keep staged candidate headers first and convert every original relative `-i` root to an absolute path under `REMOTE_DIR`. This preserves candidate overrides, retains the remote checkout for unchanged headers, and fixes every project include root consistently. This is the selected approach.
3. Remove `-cwd source`. This changes compiler semantics beyond the candidate workflow and could alter the code being inspected, so it is rejected.

## Design

When `REMOTE_TMP` is set, the remote command will build include arguments in two layers:

- Candidate overrides: absolute `REMOTE_TMP/src` and `REMOTE_TMP/src/melee` first.
- Original compile roots: each relative `-i <root>` rewritten to absolute `REMOTE_DIR/<root>`; already-absolute roots are preserved.

The wrapper will continue compiling from the staged temporary source with `-cwd source`. It will not rely on selective substitutions for only `src` and `src/melee`.

After a remote command exits zero, the wrapper will validate its captured output before announcing success. A valid dump must contain at least one line beginning `FUNCTION:` and must not contain compiler-error diagnostics. If validation fails, it will move the captured output to the requested `OUT_FILE`, print a specific diagnostic to stderr, and return nonzero. This matches the existing behavior for a nonzero remote command: inspectable partial output is retained rather than discarded.

## Testing

- Expand the fake Ninja command in `test_mwcc_inspect_script.py` with multiple relative include roots and assert the remote payload gives candidate roots first while making every original relative root absolute under `REMOTE_DIR`.
- Add zero-exit fake-inspector cases for a compiler diagnostic with a `FUNCTION:` line and for `Compilation finished` without a `FUNCTION:` line. Each must fail and preserve its output file.
- Keep the existing successful candidate and nonzero remote-failure tests.
- Verify with `pytest tests/test_mwcc_inspect_script.py -q --no-cov` and `bash -n tools/workflow/mwcc-inspect.sh`.

## Scope

Only `tools/workflow/mwcc-inspect.sh` and `tools/melee-agent/tests/test_mwcc_inspect_script.py` change. The stale-remote-ref repair from issue #1212 is intentionally preserved and is not altered.
