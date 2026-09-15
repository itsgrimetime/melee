# Issue 912: Retained-Source Simplify-Order Repair

## Problem

`melee-agent debug mutate simplify-order` can search source-shape variants for
the current repo source, but it cannot continue from a retained downhill
candidate. Issue #912 needs the command to start from a supplied retained `.c`
and retained `.pcdump`, then search further variants while preserving protected
allocator hits such as `IG44 -> r25` and trying to move `IG34` from `r29` to
`r27`.

The existing current-source-only workflow recompiles the repo TU to derive its
baseline. That loses the retained candidate's allocator state, so the matcher
cannot explore Case C residuals from the already-useful retained source.

## Scope

Extend the existing `debug mutate simplify-order` command. Do not add a new
top-level command.

The retained mode must:

- Accept `--source-file PATH` for the retained full TU source.
- Accept `--pcdump PATH` for the retained baseline pcdump.
- Use the retained source as the variant base instead of the repo source.
- Use the retained pcdump as the baseline allocator signature instead of
  recompiling the repo source.
- Treat multi-target `--force-phys` objectives as protected/residual when the
  retained baseline already satisfies some entries. For `34:27,44:25`, if the
  retained baseline has `IG44 -> r25` and `IG34 -> r29`, then `IG44 -> r25` is
  protected and `IG34 -> r27` is the residual target. Candidates that lose a
  protected mapping are rejected or terminal-labeled instead of ranked as an
  equal miss.
- Retain ranked probe sources when requested and include their paths in JSON.
- Include enough per-probe metadata for matcher agents: target score virtuals,
  source hunk, source retained path, structural guard fields when requested,
  and terminal blockers for compile/score failures.

## Design

Add retained-mode options to `mutate_simplify_order_cmd`:

- `--source-file PATH`: full unit source used as the search baseline.
- `--pcdump PATH`: retained baseline pcdump. Required when `--source-file` is
  present so the command does not silently fall back to current-source state.
- `--json/--no-json`: emit a machine-readable report in addition to existing
  text mode.
- `--retain-probes DIR`: write ranked candidate sources under this directory.
- `--checkdiff-guard/--no-checkdiff-guard`: include structural guard metrics
  when scoring retained probes.
- `--protect-force-phys IG:PHYS[,IG:PHYS...]`: optional explicit protected
  mapping. When omitted, entries in `--force-phys` that are already satisfied
  by the retained baseline are protected automatically.

The command already resolves the real source unit for cflags and aliases. In
retained mode, the `FunctionContext.source_path` points to `--source-file`.
The search core compiles each generated full-unit candidate with the real unit
source as its `unit_source` compile context, so the temporary source is compiled
as the retained full TU but with the correct Melee build settings.

The search result shape gains a scored-candidate retention list for candidates
that compile and pass the protected/precolor gates. Rejected candidates still do
not retain source text. Each retained record can write a `.c` file and attach:

- `provenance`
- `rank`
- `source_retained`
- `source_hunk`
- `target_score`
- `structural_guard`
- `terminal_blocker`
- force-phys hit counts from the simplify search score
- protected/residual force-phys status

This keeps the feature narrow: the search still uses existing mutation
adapters (`decl-orders`, `insert-alias`, `holder-lifetime`, `type-change`, and
optional permuter harvest) while retained mode fixes the missing baseline,
protected-force-phys, and candidate-retention affordances. If the bounded
adapter set cannot move the residual target while preserving protected entries,
the JSON report must say so with a terminal blocker.

## Tests

Add focused tests in `tools/melee-agent/tests/test_mwcc_debug_simplify_search_cli.py`:

- `--source-file` without `--pcdump` fails early.
- Retained mode reads the supplied baseline pcdump and does not compile the
  repo source to derive baseline state.
- Generated retained probes compile through the real unit source context.
- Core search rejects candidates that lose protected force-phys entries.
- Core search ranks residual IG34 progress while preserving protected IG44.
- JSON retained output includes `source_retained`, `source_hunk`, force-phys
  hit metadata, and target-score/structural-guard fields when scoring is
  requested.
- Probe files are written to `--retain-probes` with stable rank/provenance
  names.

## Verification

Run the narrow test module plus a command-level smoke:

- `python -m pytest --no-cov tools/melee-agent/tests/test_mwcc_debug_simplify_search_cli.py -q`
- `python -m py_compile tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/mwcc_debug/simplify_search.py`
- A retained-mode smoke using issue #912 artifacts with `--source-file`,
  `--pcdump`, `--force-phys 34:27,44:25`, `--json`, and `--retain-probes`.

## Non-Goals

- Do not invent new mutation primitives for Case C in this pass.
- Do not run decomp-permuter.
- Do not apply retained probes to the real source automatically.
- Do not require remote scoring for every retained probe; use existing
  score-source paths when explicit scoring is requested.
