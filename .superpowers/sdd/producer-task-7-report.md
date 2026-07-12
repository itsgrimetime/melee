# Producer Task 7 Report: Retail PCode Instrumentation Gate

## Status

Feasibility-blocked for proof promotion. Safe diagnostic producer work is
implemented and tested, but the installed GC/1.2.5n registry remains empty and
the PCode instrumentation gate remains explicitly unpromoted. No address, site,
opcode rule, or proof tuple was guessed.

## Capability and asset preflight

The required audit ran first:

```text
melee-agent capabilities search "retail pcode operand lifecycle mutation emission proof"
```

It selected the existing `debug retro probe-backend-pcode` and `/mwcc-retro`
surfaces; no CLI was added. The active-worktree setup used ignored symlinks to
the shared compiler/vendor assets, without editing or building the shared
checkout. `ensure_for_root()` returned `rebuilt=False` with retrowin32 pin
`11dbea5a68af21121511a6577a2d4a2f917da6dc` and cadmic pin
`bad9cea2423bed957188c930086f9dabe669d30c`. The retail compiler digest is:

```text
ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c
```

No compiler/vendor binary or ignored audit artifact is tracked.

## Strict TDD record

The first focused RED run reported `7 failed, 97 passed`. Missing behaviors
were complete raw PCodeArg reads, exact same-run event anchors, atomic mutation
capture, fail-closed partial-site coverage, legacy-v1 filtering, and exact
struct-map/proof inventory gates. Later RED cases separately established raw
reader gating, map-probe unpromoted output, explicit installed gate state, and
atomic PCode sidecar publication/correlation.

The final focused command was:

```text
cd tools/melee-agent
python -m pytest \
  tests/test_retro_backend_pcode_snapshot.py \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_map_evidence.py -q -o addopts=''
```

Fresh final output: `110 passed in 0.54s`.

Implemented diagnostics:

- every enabled PCode snapshot reads all 12 bytes of every inline PCodeArg and
  records kind, secondary flags, register/payload prefix, full raw hex, and
  SHA-256; raw reads are withheld unless the complete installed layout gate
  passes;
- event helpers add exact PCode event sequence, proof site ID, runtime address,
  allocation generation, and stopped lifecycle position;
- mutation inputs and outputs are captured before either side is published;
- coverage recomputes expected/hooked site counts, sequence continuity, caps,
  drops, truncation, and errors, and always withholds capability pending the
  independent Task 6 replay;
- Task 7 events never enter `backend-events.v1.jsonl`;
- a deterministic fsync-plus-replace PCode sidecar uses the exact Task 5
  capture-attempt identity and preserves prior valid output on publication
  failure; and
- the map probe reports the exact layout/proof errors with `status:
  unpromoted` and an empty capability list.

## Static audit evidence and blocker

`file`, `objdump -h/-p/-t/-d`, `strings`, the pinned cadmic parser, and the
existing mwcc-debug reverse-engineering notes were inspected. The compiler is
a stripped PE32 with no symbol table. Independent evidence agrees on:

- PCode opcode at `+0x14`, arg count at `+0x1a`, args at `+0x1c`;
- 12-byte inline PCodeArg records;
- PCodeArg kind at `+0`, secondary flag byte at `+1`, and register/payload at
  `+2`; and
- formatoperands dispatch over raw opcode IDs and successive 12-byte operands.

The binary also retains module strings including `Operands.c`,
`PCodeUtilities.c`, `PCodeAssembly.c`, `Scheduler.c`, and `Coloring.c`.

An exhaustive whole-PE Ghidra recovery was attempted with:

```text
analyzeHeadless build/ghidra-project mwcc125n \
  -import build/compilers/GC/1.2.5n/mwcceppc.exe \
  -overwrite -analysisTimeoutPerFile 300
```

It remained at `ANALYZING all memory and code` after about seven minutes,
beyond the 300-second bound, with the Java process idle. It was interrupted and
reported immediately as issue **#1239**.

Consequently the audit could not prove exhaustive inventories for:

1. every ObjObject allocation/free/recycle site;
2. every PCode allocation/free/recycle site;
3. every allocator register-operand rewrite path;
4. every PCode create/delete/reorder/clone/replace mutation path;
5. every final code-emission path and PCode-to-machine mapping; or
6. the complete opcode mnemonic and operand-role/allocatability tables.

The exact feasibility blocker was reported as issue **#1240**. Because the
static gate failed first, the requested DrawFighterHeaders, named-local,
address-taken/multi-virtual, and FPR/spill live promotion probes were
intentionally not run. Bounded dynamic survival cannot replace the missing
exhaustive static proof.

## Promotion state

`tools/mwcc_retro/tables/gc_125n.json` records the exact compiler digest but:

```text
instrumentation_proofs: []
pcode_instrumentation.validated: false
proof_id: null
proof_sha256: null
operand_rewrite_site_ids: []
operand_mutation_site_ids: []
code_emission_site_ids: []
```

Therefore no proof digest exists, no tuple was promoted, and no altered-proof
positive case was fabricated. Pure negative tests prove altered site
inventories fail closed.

## Regression and static verification

Recorded green evidence before final handoff:

```text
Task 7 focused: 110 passed
Task 2 proof/registry: 51 passed
Task 5 selected object/IG/frame/one-pass/PCode: 101 passed, 77 deselected
Task 6 lineage plus adjacent proof/object/identity/bundle: 422 passed
```

Scoped production and focused-test Ruff checks passed; six non-legacy scoped
files passed `ruff format --check`. The legacy runtime test file passed Ruff
`E,F,W` checks without repository-wide formatter churn. JSON parsing,
`py_compile`, `git diff --check`, and scans for compiler helper calls, the
forbidden `0x4C1720` accessor, invented site IDs, and invented site addresses
all exited zero.

## Concerns

The diagnostic event APIs and atomic sidecar are ready for exact promoted sites,
but they deliberately remain dormant for proof-capable capture. Promotion
requires resolving #1239/#1240 and independently reviewing the complete static
and bounded-live proof chain; weakening any validator would violate the design.

## Important review remediation

The Task 7 review identified two fail-open surfaces in the unpromoted
diagnostic implementation. A new strict RED run reported `16 failed, 114
passed`: the capability gate accepted a promoted registry/gate without an
embedded proof, and producer coverage normalized malformed hook/event input
instead of proving exact coverage. A later adversarial RED case reproduced an
uncaught `TypeError` for a list-valued event kind, and a final RED case
reproduced a hostile `Mapping.get()` exception escaping the proof gate.

The remediation now:

- always validates the independent proof registry, requires and safely
  materializes a proof mapping, reuses Task 2 closed-shape validation and RFC
  8785 proof hashing, and binds the exact compiler/proof/digest tuple;
- requires every proof and installed-gate site inventory to be nonempty,
  unique, canonically ordered, and byte-for-byte equal;
- reports producer coverage complete only for the exact set of string hook
  IDs and a nonempty, closed event list with known kinds, family-correct sites,
  and non-boolean contiguous sequence integers;
- converts malformed errors, caps, drops, truncation flags, nested event
  values, short/non-byte PCodeArg reads, and publication failures into explicit
  partial diagnostics while always returning `capabilities: []`; and
- preserves the prior valid sidecar if atomic replacement fails.

Fresh post-remediation verification:

```text
Task 7 focused: 132 passed
Task 2 proof/registry: 51 passed
Task 5 selected object/IG/frame/one-pass/PCode: 114 passed, 78 deselected
Task 6 lineage plus adjacent proof/object/identity/bundle: 422 passed
```

Scoped Ruff checks, legacy-runtime `E,F,W`, `py_compile`, JSON parsing, and
`git diff --check` all exit zero. The current Ruff formatter would reformat the
five touched non-runtime files, but it also reports the same result for each
file's pre-remediation `HEAD` content; no repository-wide legacy formatting
churn was introduced. The installed registry remains empty and
`pcode_instrumentation.validated` remains false. No live probe or static audit
was rerun during remediation.
