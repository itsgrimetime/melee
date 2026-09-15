# Signature Call-Type Audit Design

## Problem

`checkdiff` classifies many unresolved functions as signature/type mismatches
when call shape, argument setup, or return handling differs. Today the matching
agent sees a broad label and raw assembly, but not the source levers that might
fix it: helper prototypes, argument width/signedness, field types, return
types, or narrow call-site casts.

The existing `debug suggest casts` command starts from explicit source casts.
Issue #428 needs the inverse workflow: start from `checkdiff` call-prep
differences around `bl` sites, correlate them with current source calls and
types, and rank bounded source actions.

## Goals

- Add a read-only diagnostic for the `signature-type-mismatch` and
  signature-call-type buckets.
- Consume either a saved `tools/checkdiff.py --format json` payload or run live
  checkdiff when no payload is supplied.
- Inspect same-target call sites and classify call-prep differences:
  GPR/FPR bank mismatches, sign/zero-extension width mismatches, load-kind
  differences, call-target shape differences, and argument-register source
  differences.
- Correlate each call-prep finding with the source call, argument expression,
  explicit casts, local/parameter types, simple field expressions, visible
  prototypes, and same-TU helper definitions when available.
- Emit ranked candidate actions with confidence, affected call sites, and
  bounded patch descriptors only for low-blast-radius cases:
  remove a single default-promotion-sensitive explicit call-site cast, or
  inspect/change a same-TU static helper prototype.
- Support optional validation that compiles temporary patched source copies,
  runs checkdiff on temporary objects, reports the delta, and leaves real source
  untouched.
- Provide JSON output for agent consumption and concise text output for humans.

## Non-Goals

- Do not automatically rewrite headers or cross-TU public prototypes.
- Do not attempt whole-project type inference.
- Do not replace `debug suggest casts`; keep explicit-cast linting separate.
- Do not auto-apply candidate patches. Validation must use temporary source
  copies and must not edit the real source file.
- Do not require pcdump or MWCC inspector output for the MVP.

## Command

Add:

```bash
melee-agent debug suggest signatures -f <function>
melee-agent debug suggest signatures -f <function> --checkdiff-json fn.json --json
melee-agent debug suggest signatures -f <function> --checkdiff-json fn.json --validate
```

The command belongs under `debug suggest` because it produces source-direction
suggestions. `--checkdiff-json` makes it deterministic and testable. Without
that option, the command runs checkdiff with fingerprinting disabled and
`--no-build` by default; pass `--build` to allow the initial checkdiff run to
rebuild:

```bash
python tools/checkdiff.py <function> --format json --no-fingerprint --no-build
```

with fingerprinting disabled.

## Data Flow

1. Load checkdiff JSON and validate that it has `target_asm`, `current_asm`,
   `diff`, and `function`.
2. Resolve the owning translation unit and read `src/<unit>.c`.
3. Extract the requested function and its source call sites using the existing
   cast-audit parser.
4. Parse target/current assembly into lightweight instructions.
5. Pair `bl <target>` sites by target name and ordinal.
6. Also align the call sequence by ordinal so missing, extra, or different call
   targets produce `call-target-shape-mismatch` findings instead of
   disappearing from same-target pairing.
7. For each paired call, scan a small window before `bl` and summarize final
   writes to ABI argument registers:
   `r3-r10` for GPR arguments and `f1-f13` for FPR arguments.
8. Compare target/current call-prep summaries and classify differences.
9. Match each assembly call pair to the same source call target/ordinal.
10. Rank candidate source actions using source evidence:
    explicit casts, declared local/parameter types, call argument text, simple
    field-expression text, visible prototypes, and same-TU static helper
    definitions.
11. Optionally validate removable call-site cast descriptors by compiling a
    temporary patched source copy, running checkdiff against that temporary
    object, and leaving the real source file untouched.

## Finding Kinds

- `argument-bank-mismatch`: target prepares an FPR argument where current uses a
  GPR argument, or the reverse. Candidate actions focus on prototype argument
  type, explicit call-site casts, and helper call signatures.
- `argument-width-mismatch`: one side inserts `extsb`, `extsh`, `clrlwi`,
  `rlwinm`, or similar width shaping before a GPR argument and the other side
  does not. Candidate actions focus on signed/unsigned width, local casts, and
  parameter type.
- `argument-load-kind-mismatch`: one side uses integer loads such as `lwz`,
  `lbz`, `lha`, `lhz` and the other uses float loads such as `lfs`/`lfd`, or
  different width loads for the same argument register. Candidate actions focus
  on field type and explicit casts.
- `argument-source-register-mismatch`: both sides write the same ABI argument
  register but from different source registers. Candidate actions are lower
  confidence and point at local temp lifetime/order or argument expression
  shape.
- `call-target-shape-mismatch`: calls differ by target/ordinal. Candidate
  actions point at prototypes, return types, or inline boundary differences.

## Candidate Actions

Each action reports:

- `kind`: `remove-call-arg-cast`, `same-tu-static-prototype-audit`,
  `call-argument-type-audit`, `field-type-audit`, `local-temp-shape-audit`,
  or `call-target-shape-audit`.
- `confidence`: `high`, `medium`, or `low`.
- `affected_call_sites`: one or more source call-site descriptors with
  `source_file`, `line`, `call_target`, `arg_index`, `arg_text`,
  `declared_type`, and prototype evidence when available.
- `reason`: one actionable sentence.
- `patch`: present only for bounded one-site removable cast actions. The patch
  descriptor contains the line number, exact `old` text, and exact `new` text.
- `validation`: absent unless `--validate` is requested.

Patch descriptors are intentionally conservative. The MVP only emits them when
an argument begins with an explicit cast whose removal can be represented as an
exact one-line replacement and prototype evidence says the call is
default-promotion sensitive. The inner expression must also have positive type
evidence matching the expected ABI bank, such as a declared integer expression
for an expected GPR argument. Unknown inner expressions and expressions already
declared in the cast's ABI bank produce audit-only actions. Fixed-prototype
calls, including same-TU static helpers with declared parameter types, do not
receive remove-cast patches from ABI-bank evidence; they receive prototype/type
audit actions instead.

## Validation

`--validate` validates only descriptors with `kind == "remove-call-arg-cast"`.
For each descriptor:

1. Read the original source file bytes and build patched source text in memory.
2. Replace the exact line fragment once in the in-memory text.
3. Write the patched text to a temporary source file under
   `build/mwcc_debug_cache/probes/signature_audit/.../*.c`, not under `src/`.
4. Compile it with the real TU's flags using the existing `debug dump local
   --unit-source src/<unit>.c --keep-obj <tmp.o>` path.
5. Under the same repo-wide checkdiff lock used by other debug verify paths,
   copy the temporary object into the build object slot, run
   `python tools/checkdiff.py <function> --format json --no-build`, parse the
   result, and restore the original object in `finally`.
6. Confirm the real source file hash still matches the pre-validation hash.

If validation cannot run or parse output, the result is reported as
`status="failed"` with an error message. A candidate is actionable only when
the parsed match percentage improves or checkdiff reports a match.

## Testing

Add unit tests for:

- parsing call-prep summaries from synthetic target/current assembly;
- matching source call ordinals to assembly call ordinals;
- producing a high-confidence remove-cast candidate for a GPR-vs-FPR mismatch;
- refusing to emit a remove-cast patch when a fixed prototype controls ABI
  argument passing;
- producing a same-TU static helper prototype audit candidate without a patch;
- producing an explicit `call-target-shape-mismatch` for unmatched call targets;
- aggregating repeated same-root findings across affected call sites;
- JSON/text CLI behavior from a saved checkdiff payload without running
  checkdiff;
- validation keeping the real source unchanged and annotating candidate deltas
  using a monkey-patched candidate-source runner.

Add command-level smoke checks for:

```bash
melee-agent debug suggest signatures --help
melee-agent debug suggest signatures -f <fn> --checkdiff-json <fixture> --json
```
