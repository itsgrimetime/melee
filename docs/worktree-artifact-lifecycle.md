# Worktree artifact lifecycle

`tools/worktree-doctor.py` can report and safely remove old generated
artifacts from Melee worktrees, and can reuse immutable compiler/tool files in
new worktrees. The commands are intentionally conservative: they manage build
products, never source or repository state.

## Report and cleanup

By default, artifact discovery is limited to the worktrees registered by the
current repository's `git worktree list`. To inspect additional locations, pass
one or more explicit roots with `--scan-root`; only directories independently
identified as Git worktrees beneath those roots are considered.

Only direct `build/` and `.cache/` directories are candidates. A directory is
eligible only when every regular file is ignored by that worktree's Git
configuration and it contains no tracked files, non-ignored files, symlinks,
or special files. The main checkout is reported but is never eligible for
removal. The worktree running the command is likewise reported but protected
from planning and removal. Any active local process that refers to a worktree
or candidate also excludes it from cleanup.

The default thresholds require at least seven days since the newest artifact
file and at least 1 GiB of content. Adjust them when needed:

```bash
python tools/worktree-doctor.py artifacts report --json
python tools/worktree-doctor.py artifacts cleanup \
  --min-age-days 7 --min-bytes 1073741824 --json
```

`cleanup` is a dry run unless `--apply` is supplied. The apply path repeats all
Git, filesystem, process, age, and size checks immediately before deletion, so
an artifact that changes after reporting is retained instead of removed:

```bash
python tools/worktree-doctor.py artifacts cleanup \
  --min-age-days 7 --min-bytes 1073741824 --apply
```

## Shared immutable assets

The asset cache lives at
`~/.cache/melee-agent/worktree-assets/v1/<platform>-<machine>`. It contains
only validated, read-only copies of files below these paths:

- `build/compilers/`
- `build/tools/`
- `tools/table-typer/table-typer`

It does not contain object files, build state, reports, diagnostics, virtual
environments, or source. Seed a cache explicitly, or hydrate a worktree and
allow it to seed from a known source checkout when the cache is absent:

```bash
python tools/worktree-doctor.py assets seed --source /path/to/melee
python tools/worktree-doctor.py assets hydrate --asset-source /path/to/melee
```

Hydration verifies the cache manifest and SHA-256 digests, then creates only
file-level symlinks beneath real consumer directories. Existing real files and
unexpected symlinks are preserved and reported rather than overwritten.

`tools/workflow/pr-worktree.sh create` runs hydration after base-DOL setup,
using the main checkout as its seed source. A missing or invalid cache, or a
hydration error, prints a warning but never prevents creation of an otherwise
usable PR or WIP worktree.
