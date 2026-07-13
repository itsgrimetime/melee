# MWCC Retro Whole-PE Lifetime Proof Design

Date: 2026-07-12

Status: Approved by explicit autonomous handoff for issue #1240

## Goal

Produce, independently audit, and promote one exact
`mwcc-retro-lifetime-proof.v1` for the retail GC/1.2.5n compiler executable
whose SHA-256 is
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
The proof must close every relevant executable control-flow and value-flow
path, describe all ObjObject and PCode lifecycle/rewrite/mutation/emission
sites, describe all 468 opcodes and their concrete operand layouts, and drive
the existing bounded map and PCode probes without any placeholder proof or
hook coverage.

The completed feature is trustworthy only when the deterministic static proof,
the installed runtime hook inventory, four live compiler runs, and the exact
promotion registry tuple all agree. Dynamic survival is corroboration, not a
replacement for exhaustive static analysis.

## Non-goals

- Do not merge the reporter worktree's full commit stack.
- Do not port the causal differencer, Producer Task 9, Producer Task 10, or
  unrelated matcher work.
- Do not add another top-level CLI command. Extend the existing
  `debug retro probe-backend-map` and `probe-backend-pcode` flows.
- Do not make Ghidra function ownership authoritative.
- Do not publish generated compiler binaries, Ghidra projects, or live probe
  output.
- Do not introduce a `v2` proof migration unless an old-shape proof is found
  outside this unmerged branch.
- Do not weaken any existing proof, registry, lineage, object, frame, event,
  or candidate-code validator.

## Established evidence

The exact input is a PE32 Intel 80386 executable with image base `0x00400000`,
entry point `0x00401000`, and executable `.text` beginning at `0x00401000`.
The existing proof registry is empty and the PCode instrumentation gate is
disabled, so the unmerged v1 operand schema can be corrected in place.

The retained bounded audit established useful lower bounds, but also proved
that recovered Ghidra function bodies are incomplete:

- 3,187 recovered internal Ghidra functions and 27,020 direct calls in their
  bodies.
- 1,861 raw/Ghidra-union compiler-arena calls versus 1,825 within recovered
  function bodies.
- 962 raw calls to selected PCode helpers versus 773 within recovered bodies.
- 102 raw calls to the PCode unlink helper versus 59 within recovered bodies.
- A 468-way opcode dispatch in `formatoperands` at `0x004C4BF0`, using a table
  at `0x0056287C`, was not owned by a recovered Ghidra function.
- The 468-row opcode metadata table begins at `0x005654B0`, with 16-byte rows.
- Allocator rewrite at `0x004CE1A0` changes only the unsigned 16-bit payload at
  `PCodeArg +2`; it leaves kind and flags unchanged.

Those counts are regression cross-checks, not hard-coded completeness claims.
The new analyzer must reproduce or explain every difference from them.

## Approaches considered

### Selected: raw whole-PE analysis with independent Ghidra cross-check

Recover relevant code, control flow, jump tables, calls, values, object types,
and field effects directly from the exact PE. Use the validated Ghidra project
only to compare recovered instructions, entries, calls, and references. This is
the only approach that addresses code outside Ghidra-owned bodies while
retaining an independently reviewable cross-check.

### Rejected: extend the Ghidra exporter alone

The current exporter iterates `Function.getBody()`. That is precisely the
boundary that omitted allocator/helper calls and `formatoperands`. Adding more
Ghidra decompilation does not prove that missing bodies or direct field writes
have been closed.

### Rejected: representative dynamic tracing

Runtime probes can validate hook mechanics and concrete traces, but four or
even hundreds of compilations cannot prove that a stripped compiler contains
no alternative lifecycle, mutation, or emission path. Dynamic-only promotion
would violate the proof basis.

## Trust boundary and phase ordering

The trust chain is deliberately one-way:

1. The exact compiler hash gates all static analysis.
2. Raw PE recovery produces bounded CFG and instruction ownership evidence.
3. Interprocedural value/type analysis produces lifecycle and mutation
   evidence.
4. Opcode/constructor analysis and site evidence produce a canonical proof.
5. The proof validator recomputes shape, ordering, raw operand semantics, and
   RFC 8785 SHA-256. The proof digest transitively binds a separate canonical
   runtime-hook manifest digest.
6. Runtime installation requires an independently bound exact tuple, the exact
   bound hook manifest, and an exact proof-to-hook-plan semantic bijection.
7. Four live probes validate event chronology, generations, lineage, and code
   emission.
8. Only then is the identical tuple copied into the installed registry and the
   gate enabled.

Before promotion, live probes use a generated candidate table in their ignored
output directory. The candidate table is validated by the same production
registry and installed-site validators as the final table, but it does not
modify tracked `gc_125n.json` or publish a capability. Promotion copies the
already reviewed, already exercised tuple and site lists byte-for-byte; there
is no relaxed "candidate" validator.

Any failure in an earlier layer prevents later layers from claiming a
capability. A downstream success never overrides an upstream gap.

## Architecture

### Strict PE model

Extend `tools/mwcc_retro/pe.py` from a minimal byte mapper into a strict,
read-only PE32 proof boundary. It will expose the DOS/PE headers, x86 machine
type, optional-header magic, image base, entry point, data directories,
sections and characteristics, imports, exports, base relocations, and exact
mapped ranges.

Loading fails on a wrong hash, wrong machine/magic, truncated structure,
overlapping raw or virtual ranges, invalid directory, executable bytes outside
declared executable sections, or a read that is not wholly mapped. No caller
may silently receive a short read.

### Deterministic x86 CFG recovery

Add `tools/mwcc_retro/x86_cfg.py`. It uses Capstone in x86-32 detail mode with
skip-data disabled. An address-priority worklist is seeded from:

- the PE entry point and exports;
- exact direct call and branch targets;
- executable targets proven through relocations and bounded pointer tables;
- independently validated audit anchors;
- recovered callback tables; and
- independently decoded function-pointer initializers.

Basic blocks split at branch targets, conditional and unconditional control
flow, calls, returns, and indirect transfers. Instructions, blocks, edges,
tables, and diagnostics are emitted in numeric canonical order. Direct
`E8 rel32` candidates are scanned independently across the executable bytes;
every valid raw candidate must be owned by the recovered CFG or reported as an
unresolved blocker. Embedded data that resembles a call is explained by exact
instruction/data ownership rather than counted blindly.

Computed branches and calls are resolved only from proven finite tables or
proven finite abstract target sets. A jump table records the guard that bounds
it, entry width, base, index range, every raw entry, and every executable
target. `formatoperands` is an explicit acceptance case: the recovered graph
must contain all opcode IDs `0..467`, all 468 targets, and the shared dispatch
closure through its exit region. The analyzer does not special-case those
targets as truth; it requires the ordinary table-recovery algorithm to derive
them and uses the known facts as a regression assertion.

Conflicting decodes, branches into instruction interiors, unresolved relevant
computed transfers, or unexplained executable regions fail closed.

### Interprocedural value and type analysis

Add `tools/mwcc_retro/backend_lifetime_audit.py`. It consumes only the strict
PE and raw CFG artifacts. The analysis is a deterministic SCC/fixed-point
abstract interpreter over x86 registers, stack arguments/locals, return values,
statically addressed memory, and call summaries.

The value lattice contains:

- exact integers and bounded finite sets;
- affine values needed for layouts such as `0x28 + 0x0C * arg_count`;
- exact image/code/data pointers;
- null;
- typed `PCode`, `PCodeArg`, `ObjObject`, arena, block, and list pointers with
  exact byte offsets and allocation-origin provenance; and
- unknown with the exact unsupported instruction or merge that caused it.

Summaries describe argument-to-return/global flow, allocation origins,
returned types, typed reads/writes, list effects, and helper effects. Unknown
is permitted on an irrelevant slice. If an unknown can influence a relevant
pointer, allocation size, branch, indirect target, call argument, field store,
or emitted code mapping, it is an unresolved blocker rather than a widening
shortcut.

The analysis must classify all discovered calls to the four compiler arenas,
not only adjacent immediate-size calls. It starts from the six known PCode and
28 high-confidence ObjObject allocation candidates, proves or expands those
sets, and reports any expansion for explicit review. It also proves cache/reuse
transitions, temporary/persistent arena rewind/release boundaries, and
generation-changing physical reuse.

All calls to `0x0049D010` are classified by path as deletion or as
move/reinsert/replace. The analysis inventories every direct write to PCode
links, opcode, flags, argument count, argument kind, argument flags, argument
payload, and inline argument bytes. Clone, reorder, replace, spill, coalesce,
and allocator rewrite paths receive explicit provenance chains.

Final emission closure must prove the final walker, the sole per-PCode encoder,
the final buffer write, pseudo-op handling, and the exact relationship from a
PCode and its operands to emitted byte ranges, relocations, and machine
register fields. Alternative encoders or buffer-write paths expand the
inventory and block promotion until reviewed.

### Explicit bounds

All configurable analysis caps live in a single frozen configuration object
and are embedded with observed high-water marks in the audit summary. The
implementation plan will set conservative limits above the exact compiler's
observed values for decoded instructions, blocks, edges, functions, jump-table
entries, finite target/value sets, abstract states, SCC iterations, and summary
iterations.

Reaching any cap is a hard proof failure. A cap is not a truncation mechanism.
Increasing a cap requires re-running both deterministic generation passes and
reviewing the resulting artifact delta.

### Static artifacts

Each `probe-backend-map --static-only` run writes a versioned ignored audit
directory containing:

- `raw-pe-cfg.v1.jsonl`: canonical instructions, blocks, edges, calls, and
  jump tables.
- `raw-ghidra-crosscheck.v1.json`: numeric raw-versus-Ghidra instruction,
  flow, reference, and ownership deltas without granting Ghidra completeness
  authority.
- `backend-lifetime-sites.candidate.v1.json`: allocations, reuse/free
  boundaries, unlink classifications, field writes, mutation/rewrite/emission
  sites, and provenance paths.
- `opcode-layouts.candidate.v1.json`: all opcode metadata, constructor evidence,
  descriptors, expansions, and register domains.
- `backend-lifetime-audit.v1.json`: compiler identity, bounds/high-water marks,
  cross-check deltas, artifact hashes, unresolved diagnostics, and
  `proof_ready`.
- `gc_125n_lifetime_hooks.candidate.json`: canonical runtime hook operations,
  breakpoint phases, ABI/memory capture sources, pairings, and hit policy for
  every proof site.
- `gc_125n_lifetime_proof.candidate.json`: emitted only when
  `proof_ready=true` and accepted by the production proof validator.
- `gc_125n.candidate.json`: ignored production-shape table containing the
  exact candidate proof registry tuple and rewrite/mutation/emission gate used
  unchanged by live probes.
- `REPORT.md`: human-readable completeness argument generated from the same
  inventories.

Publication order is acyclic: raw CFG, Ghidra cross-check, lifetime sites,
opcode layouts, audit summary, canonical hook manifest and digest, canonical
proof containing the manifest digest and its digest, candidate table containing
that proof tuple and exact site gate, then the report.

Digest-bearing artifacts exclude timestamps, elapsed time, host-specific
paths, and unordered containers. Publication uses a temporary file, flush,
`fsync`, and atomic replace. A second run in a separate output directory must
produce byte-identical canonical artifacts and identical digests.

The reviewed candidate proof and its digest-bound hook manifest are then
tracked at `tools/mwcc_retro/tables/gc_125n_lifetime_proof.json` and
`tools/mwcc_retro/tables/gc_125n_lifetime_hooks.json`. The complete full-CFG
JSONL may remain ignored because it is deterministically reproducible from the
exact binary; the tracked proof, manifest, generator, tests, and human evidence
document are the review surface.

Ghidra cross-check input is exported from the validated exact-hash project.
Differences are reported by address and category. Ghidra may reveal a raw
recovery bug and thereby block the proof, but a missing Ghidra owner does not
erase correctly recovered raw code.

## Corrected unmerged proof schema

The root schema identifier remains `mwcc-retro-lifetime-proof.v1`; mode remains
`allocation-generation`; proof basis remains
`exhaustive-static-callgraph-and-disassembly`; and proof ID remains
`gc-1.2.5n-backend-entity-allocation-trace.v1`.

The root proof adds `runtime_hook_manifest_sha256`, a 64-character lowercase
SHA-256 of the RFC 8785 canonical hook manifest. The compiler/proof/digest
promotion registry shape does not change: its proof digest now transitively
binds the exact hook semantics.

The existing lifecycle and PCode site row shapes remain closed. Each site must
form an exact site-ID/address/family bijection with one row of the bound hook
manifest. Site-specific capture remains implemented by closed, reviewed
runtime handlers, but the manifest binds every semantic input those handlers
are expected to use; executable code is not trusted merely because it installed
a breakpoint at the right address.

### Runtime hook manifest

The hook manifest has the closed root fields `schema_version`,
`compiler_executable_sha256`, `proof_id`, and `sites`. Its schema is
`mwcc-retro-runtime-hooks.v1`. It does not include the proof digest, avoiding a
digest cycle; the proof includes the manifest digest.

Each canonical site row contains exactly:

```json
{
  "site_id": "pcode-rewrite-004ce1e7",
  "family": "operand_rewrite_sites",
  "proof_address": 5038567,
  "operation": "operand-rewrite",
  "breakpoints": [
    {
      "phase": "before",
      "address": 5038567,
      "instruction_bytes": "66894102",
      "instruction_sha256": "3fe7c35980c7123af1a186863002ac16c91c5cab50e9c414396795753748666d"
    },
    {
      "phase": "after",
      "address": 5038571,
      "instruction_bytes": "83c10c",
      "instruction_sha256": "62caea42aef57848ad3dbd714e4437a8a55a696b4c82483b5c934ac2d96fb4f9"
    }
  ],
  "capture_sources": [
    {
      "name": "operand_address",
      "source_kind": "effective-address",
      "phase": "before",
      "operand_index": 0,
      "register": null,
      "stack_argument_index": null,
      "byte_offset": -2,
      "byte_width": 12
    }
  ],
  "pairing": "same-thread-instruction",
  "hit_policy": "probe-union"
}
```

The example uses the independently audited allocator store at `0x004CE1E7`;
the proposed deterministic site ID is not a promoted claim. The exact bytes
and digests are decoded from the pinned compiler, and generated rows must meet
the same evidence standard. `operation` is a closed family-specific enum covering
allocation, recycle, rewind, release, operand rewrite, create, delete, reorder,
clone, replace, spill, coalesce, encode, and final buffer emission.
`breakpoints` bind every before/after/return address, exact instruction bytes,
phase, and byte digest. `capture_sources` is a closed typed vocabulary:
`x86-register`, `stack-argument`, `return-register`, `effective-address`, or
`memory-at-source`. Each source binds its phase, register or stack index,
effective-address operand index, byte offset, and byte width; inapplicable
fields are explicitly null. `pairing` is exactly one of
`same-thread-instruction`, `same-thread-call-return`, or
`same-thread-function-entry-exit`.

The validator rejects an operation outside its proof family, incomplete or
overlapping breakpoint phases, instruction-byte mismatches, invalid source
coupling, omitted pointer/length inputs, and any manifest/proof site mismatch.
The runtime handler re-decodes the exact instruction and independently compares
its operands and computed capture sources to the manifest before installing a
hook. A generic data expression is never evaluated from untrusted JSON.

`hit_policy` is `per-run` for central sites that static analysis proves every
accepted compile traverses and `probe-union` for input-dependent sites. There
is no install-only or optional policy. Every per-run site must hit in each of
the four probes; every probe-union site must hit in at least one of their union.
The static audit records the control-flow justification for each policy.

### Opcode rows

Every opcode ID `0..467` appears exactly once:

```json
{
  "opcode_id": 63,
  "mnemonic": "ADDI",
  "format_string": "=r,b,m,p",
  "constructor_kind": "generic-fixed",
  "custom_constructor_addresses": []
}
```

`constructor_kind` is exactly `generic-fixed`, `generic-variadic`, or `custom`.
Generic rows have no custom addresses. Custom rows have a nonempty, ascending,
unique list of statically proven constructor addresses. Opcodes 3, 4, 12, 13,
15, 16, and 199 must be represented from their audited concrete constructors;
`?` or `t` may not be guessed through the generic parser.

### Operand descriptors

Operand rules describe layout descriptors, not already expanded runtime
indices:

```json
{
  "opcode_id": 63,
  "descriptor_index": 0,
  "format_code": "r",
  "expansion": {"kind": "one", "count": 1},
  "raw_arg_kind_id": 0,
  "role": "def",
  "register_form": "gpr",
  "class_id": 0,
  "virtual_kind": "r",
  "state_rules": [
    {
      "capture_stage": "allocator_input",
      "register_flags_mask": 255,
      "register_flags_value": 2,
      "register_value_min": 32,
      "register_value_max": 65535,
      "allocation_state": "virtual"
    }
  ]
}
```

The numeric values above illustrate shape only. Promoted masks and ranges come
from exact static evidence and live corroboration; examples are never copied as
compiler semantics.

Expansion kinds are closed:

- `one` consumes one operand and has count 1.
- `fixed` consumes the exact count of at least two operands; `Y` is fixed eight.
- `remaining` has count null, is the final descriptor, and consumes the exact
  nonnegative runtime remainder; `V` uses this form.

`#` is a constructor calling-convention marker, never an operand. Descriptor
expansion must consume exactly `arg_count`; negative or leftover operands fail.

Register forms and allocator coupling are exact:

| Form | Raw kind | Class | Virtual kind | State family |
|---|---:|---:|---|---|
| `gpr` | 0 | 0 | `r` | virtual/physical |
| `fpr` | 1 | 1 | `f` | virtual/physical |
| `vector` | 9 | 9 | `v` | virtual/physical |
| `special` | 2 | null | null | non-allocator |
| `cr` | 3 | null | null | non-allocator |
| `none` | audited non-register kind | null | null | no state rules |

Capture stages are exactly `allocator_input`, `mutation_output`, and
`code_emission`. For each expanded register operand, lookup filters by exact
stage, masked raw flags, and inclusive unsigned 16-bit value range. Zero or
multiple matches fail. There is no wildcard, priority, fallback, or unknown
rule. The validator rejects intersecting state rules when their stage is equal,
their value ranges intersect, and their flag predicates can match a common
byte. The static generator separately rejects masks or ranges that are broader
than the domain its opcode/allocator analysis proves; the proof validator does
not invent an unstated global register boundary.

State rules are ordered by stage rank, flags mask/value, value bounds, and
state rank. Opcode rows sort by opcode ID; descriptors sort by opcode ID and
contiguous descriptor index; custom addresses sort numerically. RFC 8785
canonicalization applies recursively to every proof object.

### Raw operand events

Every lineage inventory row retains and independently validates all 12 raw
bytes:

```json
{
  "operand_index": 0,
  "operand_lineage_id": "ol-6",
  "raw_arg_kind_id": 0,
  "raw_register_flags": 2,
  "raw_register_value": 34,
  "raw_payload_hex": "000222000000000000000000",
  "raw_payload_sha256": "a5d2d0f3e7a57443fa3502833c889484168d74dda9ff42072fad01c7473e05ab"
}
```

The validator requires exactly 24 lowercase hex characters, recomputes the
digest, decodes kind/flags/little-endian value, and compares all redundant
fields. Parsed register rows use `allocation_state`, add `register_form` and
`raw_register_value`, permit nullable class/virtual/physical fields, and obey
the form/state coupling above.

Virtual occurrences require exactly one audited rewrite before emission.
Physical and non-allocator occurrences require none. A rewrite preserves raw
kind and flags and changes only the audited payload bytes unless a separate
audited mutation event accounts for every other change. Vector lineage may be
valid while PowerPC machine-anchor capability abstains if the decoder cannot
prove vector register fields; that abstention must not silently grant an
anchor.

Coverage reports count `virtual_register_operands`,
`physical_register_operands`, and `non_allocator_register_operands` separately.

## Opcode and constructor proof

The generator reads all 468 metadata rows and exact format strings from the
pinned table. It derives the generic format-code-to-kind/role mapping from the
generic constructor control flow, including fixed and tail expansion. It then
proves concrete layouts for custom opcodes 3, 4, 12, 13, 15, 16, and 199 and
the runtime count source/bounds for variadic opcodes 1, 19, 20, 39, and 54.

Compiler-specific virtual and physical domains for GPR, FPR, and vector, plus
special and CR values, are derived from allocator initialization, class tables,
rewrite control flow, and emission constraints. No global `0..31` assumption is
carried from the current implementation. Mutation-output stages receive their
own proven state domains when they can occur on either side of allocation.

Any unknown format code, missing constructor, incomplete expansion, uncovered
opcode ID, or non-unique state rule blocks `proof_ready`.

## Runtime instrumentation

Add a shared runtime installer used by map, one-pass, and PCode probe hooks. It
loads the exact proof only after compiler SHA, closed shape, RFC 8785 digest,
independent registry tuple, bound hook-manifest digest, and exact
proof-to-hook-plan semantic bijection validation. The compiler digest is
carried into runtime capture identity.

The installer constructs a lifecycle tracker before any snapshot:

- Allocation call-site hooks capture inputs before the call and the returned
  pointer at a proven post-call address.
- Free, recycle, rewind, and release hooks capture the affected active
  identities before mutation.
- Generation increments on physical address reuse and is keyed by entity kind
  and runtime address.
- Every event receives a gap-free lifecycle sequence and the stopped
  allocation generation.

Return/post-call hooks are tracked per invocation, so nested or recursive
compiler calls cannot overwrite pending state.

Rewrite hooks atomically capture the complete 12-byte operand before and after
the audited store. Mutation hooks capture all inputs before and all outputs
after create/delete/reorder/clone/replace operations; an incomplete pair emits
no successful event and records a fatal error. Emission hooks bind the final
PCode snapshot to exact candidate bytes, relocations, ranges, and decoded
machine operand fields.

A site ID enters `hooked_site_ids` only after its bound breakpoint plan and all
capture sources are completely, uniquely, and byte-exactly installed. Expected
proof IDs must equal manifest IDs and installed IDs exactly. Duplicate
addresses, duplicate IDs, partial installs, unexpected hits, a missed per-run
site, an uncovered site after the four-probe union, sequence gaps, stale output,
malformed events, errors, drops, event caps, or truncation fail the run.

The current `proof=None`, empty proof inventories, empty `hooked_site_ids`,
absent lifecycle capture, unconditional empty capabilities, and raw-operand
drop paths are removed from proof-capable execution. Fail-closed unpromoted
behavior remains intact when no reviewed candidate or promoted proof is
supplied.

## Four live probes

The live suite uses existing source/fixture evidence to choose:

1. `mnDiagram_DrawFighterHeaders` as the required complex control case.
2. A small function with named local/frame identities.
3. A function where one address-taken object binds to multiple virtuals.
4. A function with observed FPR allocation and a spill.

The last three are selected only after a preflight trace proves the intended
behavior; a simple function is not labeled an FPR/spill case from historical
provenance alone. The current tracked unit fixtures provide named-local,
one-object-to-multiple-virtual, FPR, and spill evidence separately, but no
single tracked live fixture yet proves the fourth case. Selection and the
observed facts are recorded in the evidence document.

Every run requires the exact compiler/proof/digest tuple, exact expected and
installed site sets, no errors/drops/caps/truncation, gap-free lifecycle and
PCode sequences, correct generations, valid mutation chronology, valid
virtual-to-physical rewrite lineage, and exact emitted code mappings. A failed
case is fixed in the producer or static proof; the gate or difficult site is
not removed.

After all four runs, a union validator requires every manifest site to have at
least one hit and separately requires each `per-run` site in every run. The
tracked evidence records the sorted per-run and union hit sets. If the chosen
fixtures do not cover the manifest, the fixture selection or producer must be
corrected before promotion; an unhit site is never exempted.

## Promotion

Promotion changes exactly two tracked trust surfaces:

- add one exact `(compiler SHA, proof ID, proof SHA, promoted=true)` registry
  row; and
- set `backend_reader.pcode_instrumentation.validated=true` with the exact
  nonempty proof tuple and site-ID inventories.

The promoted values must byte-for-byte match the candidate table exercised by
all four live probes. Negative tests alter the executable digest, proof ID,
proof digest, each site family, ordering, and nested containers to prove the
installed gate fails closed.

## Testing strategy

All production changes follow test-first red/green/refactor cycles.

### Synthetic static-analysis fixtures

A small checked-in synthetic PE32 builder and golden artifacts cover direct
and conditional flow, bounded jump tables, embedded fake `E8` bytes, malformed
headers, decode overlap, unresolved computed flow, cap exhaustion, allocator
wrappers, dynamic/non-adjacent sizes, affine PCode layout, interprocedural typed
pointers, relevant field writes, delete and reinsert unlink paths, clone and
rewrite flows, and final emission.

This keeps ordinary CI independent of the ignored proprietary compiler. One
skip-if-missing exact-binary integration test runs the full analyzer and
requires the known cross-check families to be reproduced or explicitly
explained. A newly discovered valid site deliberately breaks the golden proof
until reviewed; it is never silently discarded.

### Schema and lineage adversaries

Tests reject wrong compiler SHA, malformed/hostile mappings and containers,
missing/duplicate/reordered/altered sites, missing opcode IDs, custom
constructor gaps, incomplete `V`/`Y` expansion, counted `#`, wrong kind/form
coupling, missing/overlapping/wrong-stage/out-of-range state rules, altered raw
payload bytes/hash, altered proof digest, registry mismatch, unresolved static
evidence, incomplete hook coverage, event gaps, generation errors, stale output,
drops, caps, and truncation.

The retained ADDI fixture proves the original collision: identical
opcode/kind/flags classify values 34/33 as virtual at allocator input and 0/4
as physical at code emission through exact-one state-rule matches.

### Final verification

Before merge, run all focused and adjacent `test_retro_backend_*` tests,
`test_retro_struct_map.py`, proof/lineage/object/frame/IG/PCode suites, scoped
Ruff, `py_compile`, all tracked JSON parsing, both deterministic generator runs,
`git diff --check`, and `python configure.py && ninja`. Pre-existing failures
are reproduced against the branch base and reported separately; they are not
silently ignored.

## Acceptance criteria

Issue #1240 is complete only when all of the following are true:

- The raw whole-PE CFG and interprocedural audit are deterministic, bounded,
  and have no relevant unresolved diagnostics.
- All compiler arena calls, PCode/ObjObject allocations and reuse boundaries,
  unlink paths, relevant field writes, mutations, rewrites, and emissions are
  classified from exact evidence.
- All 468 opcode rows, custom/variadic constructors, layouts, expansions, and
  state/value domains are complete.
- Two generator runs are byte-identical and the tracked proof passes the
  production validator.
- Every proof site has exactly one digest-bound runtime hook plan, every capture
  semantic is independently validated, every plan is installed, every per-run
  plan is hit in each probe, and the four-probe union hits every plan.
- Four bounded live probes pass every static, lifecycle, lineage, event, and
  code-emission gate.
- The exact tuple and site lists are promoted once, with negative registry
  tests green.
- Focused, adjacent, static, JSON, and repository build verification passes or
  separately proves an unchanged pre-existing failure.
- A broad independent branch review has no open Critical or Important finding.
- The completed branch is merged to `master`, the installed master CLI replays
  the feature, issue #1240 is resolved with the commit/digest/evidence summary,
  and the issue queue is refreshed.
