# mndiagram numeric-helper validation

Tested by Codex on 2026-09-07 (America/Los_Angeles), using Dolphin 2509.
Human confirmation is pending. The evidence validates controlled API calls,
not normal menu navigation, physical distance units, or memory-card writes.

The documentation is in `src/melee/mn/mndiagram.dox`. The only C changes remove
the five helpers' old comments, including the incorrect one-mile display-cap
claim and fixed-width `MM:SS` description. No symbols, types, or instructions
are changed.

## Scope and claim ledger

The TU has 45 configured functions. This pass covers these five contracts:

| Symbol / address | Claim tested | Contrasting observations |
| --- | --- | --- |
| `mnDiagram_IsDistanceOverflow`, `8023EA54` | Inclusive threshold depends on the byte read by `lbLang_IsSavedLanguageUS` | Language 0: 99999 is false, 100000 true. Language 1: 160933 is false, 160934 true. |
| `mnDiagram_ConvertDistanceForDisplay`, `8023EAC4` | The threshold changes the divisor; the quotient is not capped at one | Language 0: 99999 → 999, 100000 → 1, 200000 → 2. Language 1: 160933 → 5280, 160934 → 1, 321868 → 2. |
| `mnDiagram_FormatDecimalNumber`, `8023F14C` | Caller modes 0 and 2 produce integer and hundredths strings, with a NUL terminator | `(0,0)` → `0`; `(0,2)` → `0.00`; `(5,2)` → `0.05`; `(12345,2)` → `123.45`. |
| `mnDiagram_FormatTime`, `8023F238` | Nonnegative input is split into unpadded minutes and a two-digit remainder; the helper imposes no four-digit minute cap | 0 → `0:00`; 59 → `0:59`; 60 → `1:00`; 599999 → `9999:59`; 600000 → `10000:00`. |
| `mnDiagram_IntToStr`, `8023F334` | Caller-range integers produce decimal digits without padding or separators, followed by NUL | 0 → `0`; 42 → `42`; 9999999 → `9999999`; 99999999 → `99999999`. |

All five are runtime-tested within the stated scope; human review remains
pending for each. General formulas in the `.dox` combine these controlled
observations with the matching implementation. They are not exhaustive tests
of every input. Negative time, decimal modes other than 0 and 2, and the full
unsigned range of the string formatters were not validated. The distance
helpers were also tested with `UINT32_MAX`.

The remaining functions are inventoried by their existing declarations in
`mndiagram.h`: index access/navigation, percentages and totals, ranking and
sorting, popup construction/callbacks, grid/header drawing, cursor/arrow/input
callbacks, and screen initialization. Those existing names and comments were
not revalidated by this pass. No new interpretation of their fields is offered.

## Reproduce the API experiment

From the active worktree, run the bounded harness with explicit local paths:

```sh
PYTHONPATH="$PWD/tools/melee-agent" python tools/dolphin-mndiagram-contract.py \
  --dolphin /Users/mike/Applications/Dolphin-Debug.app/Contents/MacOS/Dolphin \
  --iso /Users/mike/Downloads/ssbm_v1.02_original.iso \
  --output /tmp/mndiagram-runtime.json
```

Use a free port with `--port` if 19326 is occupied. The harness launches and
terminates only its own emulator, retains a fresh temporary profile, and uses
one persistent GDB connection with the interpreter (`CPUCore=0`). It does not
attach to another emulator or change the normal Dolphin profile.

Preconditions and instrumentation:

- GALE01 v1.02; original DOL SHA-1
  `08e0bf20134dfcb260699671004527b2d6bb1a45`.
- The initial acknowledged, fenced stop was at `8000522C`, before menu
  navigation. The harness checks `GALE01` in loaded memory and compares the
  complete loaded bytes of all five functions and six callees against the
  original DOL using the active symbol addresses and sizes.
- The verified accessor at `8015CC58` is
  `806d8840 38631cb0 4e800020`: load the pointer through `r13-0x77C0`, then add
  `0x1CB0`. The verified predicate at `8000AE90` reads a byte at another
  `+0x16` and compares it to 1. With `r13=804DB6A0`, the pointer slot is
  `804D3EE0`; the observed pointer was `8045A6C0`, so the controlled byte was
  `8045C386`. The harness derives these offsets from the loaded instructions.
- Arguments are installed in `r3`–`r5`, with a temporary stack at `817EF000`,
  `r2=804DF9E0`, and `r13=804DB6A0`. Floating-point execution is enabled and
  external interrupts disabled during the invocation. LR points at the
  original stopped PC; execution stops on arrival without executing it.
- Each invocation has a 4000-instruction budget and checks every PC against
  the verified function/callee ranges. Each step requires a stop reply;
  completion requires the return PC and restored stack pointer. JSON output
  retains arguments, return values, output bytes, and the complete PC path.
- Formatter buffers are filled with `A5`. Tests require the exact expected
  string plus NUL and an unchanged suffix of the 64-byte buffer. The source's
  terminating-byte storage at `804D4FA4` is checked to contain zero.
- All 71 register slots exposed through the debugger, the controlled language
  byte, temporary stack area, and output buffer are saved and restored with
  readback checks. This is not a claim of restoring emulator time or every
  internal CPU state component. The owned emulator is terminated afterward.

The final run passed **73 cases**: 56 distance calls (14 values × two functions
× two language bytes), seven decimal cases, six time cases, and four integer
cases. Both language bytes were tested with 0, 30, 31, 99, 100, 99999, 100000,
100001, 160933, 160934, 160935, 200000, 321868, and 4294967295. Larger formatter
cases also cover the two callers' distinct limits: 99999.99, 99999:59, and
99999999. Restoration checks passed.

Local artifacts are under `/tmp/mndiagram-evidence/`: `runtime-final.json`
contains the actual observations, `runtime-final.log` the progress output, and
`baseline-*` / `final-*` the preservation records. ROMs, profiles, generated
reports, and raw execution traces are not part of the source patch. The
reproduction harness uses fork-local debugging tools; keep it out of an
upstream-only source PR unless explicitly requested by its reviewer.

An earlier harness trial used an incorrect nested-struct offset for the language
byte. Its language-1, distance-31 case returned 0 rather than the expected 1,
correctly failing the assertion. The touched state was restored. That trial
(`runtime.json`) is a setup failure, not evidence about the intended language
comparison. Decoding the verified accessor fixed the observation path; the
corrected run passed 70 cases, and the final replay added three caller-limit
cases. Only the corrected runs support the documentation.

## Static connection and limits

Identifier searches across `src` and `config/GALE01` find two caller functions for
each selected helper: `mnDiagram2_CreateStatRow` and
`mnDiagram3_PopulateRankings`. Both implementations were read, including their
unit tables and the stat-type branches. The predicate selects SIS entry `0x7F`
instead of the per-stat table entry; conversion supplies a separate number.
This is a structural caller relationship, not a runtime identification of the
rendered glyph. Feet, miles, meters, kilometers, and the units of accumulated
gameplay fields remain outside the validated scope.

The decimal and integer helpers call `mn_GetDigitCount` and `mn_GetDigitAt`,
which have signed parameters and use `powi`. Those callees, the language
predicate/accessor, and `__cvt_fp2unsigned` were read and byte-verified in the
emulator. The callers' clamps and their different output buffer sizes explain
why a formatter's `u32` declaration must not be treated as a full-domain or
buffer-capacity guarantee. No domain-widening or buffer changes were made.

## Binary preservation

The initial task checkout (`d567c22dfc`) was stale. Upstream was fetched and
merged cleanly into the isolated branch `codex/understand-mndiagram`; the
baseline revision is `09f5d4ee89ac57c4caa8cf62e39b579892b77ac3`, incorporating
upstream `05a1394fae`. The shared checkout was not changed. At baseline, `src/`
and `config/` were identical to upstream.

Before and after the documentation edit, from this worktree:

```sh
python configure.py --reloc-diffs all
ninja
python configure.py progress --reloc-diffs all
git diff --check
```

Both builds reproduced the expected DOL SHA-1 above. The entire parsed strict
`report.json` was identical before and after, including all units, functions,
sections, categories, and measures. `mndiagram.o` was byte-identical, SHA-256
`77b17441a1a36e98dd525cd4540afc0a0e19cfddb68cf2224080ec4fa2363fc5`.

| TU | Code bytes | Data bytes | Functions | Result |
| --- | ---: | ---: | ---: | --- |
| mndiagram | 20496 | 1330 | 45 | 100% code, data, functions, and all six sections |
| mndiagram2 | 8552 | 400 | 21 | 100% code, data, functions, and all five sections |
| mndiagram3 | 6432 | 272 | 9 | 100% code, data, functions, and all five sections |

With `--reloc-diffs all`, the existing global baseline reports 3847436 / 3882032
matched code bytes (99.10882%), 19705 / 19828 matched functions, 100% data,
99.998566% fuzzy match, and 1130 / 1130 linked units. These exact metrics are
unchanged. All objects are configured `Matching` and the linked DOL is exact,
but this stricter report is not globally 100%; this pass does not claim it is
or relax relocation settings to hide the discrepancy.

Clang-format left the changed C file unchanged, the new `.dox` was formatted,
and the harness passed Ruff. No human review has occurred yet.

## Contribution state (2026-09-10)

The upstream-facing change is the single commit `mn: document diagram numeric
helpers` (`9bd82e470d`) on the fork branch `pr/mndiagram-numeric-helper-docs`,
rebased onto upstream `480b044540` (#3444) and opened as draft PR
https://github.com/doldecomp/melee/pull/3445 on 2026-09-10. The `.dox` was
tightened to the one-brief-plus-one-paragraph shape used by recent upstream
`.dox` files before opening. It touches only `src/melee/mn/mndiagram.c`,
`src/melee/mn/mndiagram.dox`, and `src/melee/mn/mndiagram.h`. The header change
renames the `mnDiagram_FormatDecimalNumber` prototype parameter from `mode` to
`decimal_places` so it matches the existing definition; the `.dox` describes it
as the count of digits written after the decimal point, which follows from the
`powi(10, decimal_places)` split in the implementation and the tested
`(5, 2) → "0.05"` and `(12345, 2) → "123.45"` cases. Only 0 and 2 were
exercised at runtime.

The rebased commit was rebuilt from its worktree on 2026-09-10 with
`python configure.py && ninja && python configure.py progress`: DOL SHA-1
`08e0bf20134dfcb260699671004527b2d6bb1a45`, 1130 / 1130 linked, and
`mndiagram`, `mndiagram2`, `mndiagram3` each at 100% code, data, and functions.
The rebuilt `mndiagram.o` is no longer byte-identical to the 2026-09-07 baseline
object: the only differences are symbol-table strings for callees renamed
upstream in the interim (`HSD_GObj_CurrentInvokedProc`,
`HSD_GObjProc_RemoveProc`, `HSD_GObjFree`) and the resulting anonymous-literal
renumbering. Code bytes and the linked DOL are unchanged.

Human review of the behavioral interpretation is still pending.
