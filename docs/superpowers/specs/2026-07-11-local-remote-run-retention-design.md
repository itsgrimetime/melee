# Local Remote-Run Retention Design

**Issue:** #1235  
**Date:** 2026-07-11

## Goal

Bound locally fetched decomp-permuter `remote-runs` without deleting active,
unknown, partial, untriaged, winning, or explicitly retained evidence. Cleanup
is always a dry run unless the operator supplies `--apply`.

## Ownership boundary

This lifecycle owns only direct job directories shaped as:

```text
<perm-root>/nonmatchings/<function>/remote-runs/<job-id>/
```

The diagnostic artifact lifecycle from #1205 remains separate because its
manifest, root, and producer contracts are different. Shared filesystem-safety
helpers may be extracted only when doing so makes both ownership checks clearer.

## Commands

`melee-agent debug permute remote local-prune` inventories and plans cleanup.
It accepts `--perm-root`, `--max-age-days` (default 30),
`--max-total-bytes` (default 5 GiB), `--status-timeout`, `--json`, and
`--apply`. Text and JSON output report every protected or selected run and byte
totals by reason.

`melee-agent debug permute remote local-retain JOB_ID --reason TEXT` writes a
versioned, atomic retention marker after resolving exactly one owned local run.

## Fetch manifest

After fetching and candidate auditing, `fetch_job` atomically writes a
versioned local manifest containing the job identity, fetch timestamp,
complete/partial state, and audit summary. A partial rsync remains partial even
when useful files were recovered. Existing runs can be inventoried from strict
`remote-run/metadata.json` plus their candidate audit, but malformed legacy
metadata is protected.

## Protection policy

A run is protected when any of these conditions holds:

- its path is outside the owned direct-child shape;
- an owner or nested entry is a symlink, or the run contains tracked files;
- job metadata or the local fetch manifest is malformed or contradictory;
- the fetch is partial;
- the explicit retention marker is invalid or valid-and-retained;
- remote activity is `active` or `unknown`;
- the candidate inventory is incomplete or untriaged; or
- a triaged/verified candidate is a winner.

Candidate audit must account exactly for the actual `output-*/source.c` files.
A run is fully triaged only when every actual candidate has a valid
`melee-agent-candidate-status.json` whose source is `triage` or `verify`.
A winner is any such valid status with `kept=true`, a positive numeric `delta`,
or `match_pct >= 100`. The entire run is retained so its source, logs, objects,
and provenance remain together.

Remote activity is probed in batches, once per SSH host. A successful tmux
inventory proves whether each named session is active or stopped. SSH failure,
timeout, malformed output, or missing remote tooling produces `unknown` and
protects every affected run.

## Retention selection

Only positively stopped, complete, fully triaged, non-winning, unretained runs
are eligible. Eligible runs older than the age cutoff are selected first. If
the projected total still exceeds the global cap, the oldest remaining eligible
runs are selected until the cap is met or no eligible run remains. When
protected bytes make the target impossible, the report sets
`cap_satisfied=false`; it never weakens a guard to reach the cap.

## Apply safety

Apply acquires a lifecycle lock, rescans, recomputes the plan, and reprobes
selected remote sessions. Each deletion revalidates ownership, retention and
triage state, tracked-file and symlink guards, and the captured device/inode.
The directory is renamed to an owned sibling quarantine name, its identity and
guards are checked again, and only then is it removed. A mismatch or failed
revalidation is restored or left visible as a skipped quarantine; it is never
blindly followed or recursively deleted.

Dry-run performs no deletion. Unknown filesystem or remote state always fails
closed.

