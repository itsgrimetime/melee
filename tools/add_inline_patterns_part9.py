"""
Part 9: integer/bit manipulation and string/memory patterns
from two parallel agent surveys.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "melee-agent" / "src"))

from mismatch_db.models import (
    Example,
    Fix,
    Pattern,
    PatternDB,
    Provenance,
    ProvenanceEntry,
    Signal,
)
from mismatch_db.schema import init_db, DEFAULT_DB_PATH


PATTERNS = [
    # ---- integer / bit manipulation ----
    Pattern(
        id="align-up-power-of-two-rlwinm",
        name="Power-of-2 align-up `(x + (A-1)) & ~(A-1)` -> single `rlwinm`",
        description=(
            "Rounding `x` up to a power-of-2 alignment compiles to "
            "`addi rD, rS, A-1` + `rlwinm rD, rD, 0, MB, ME`. The `rlwinm` "
            "clears the low bits without needing `andi.`. Canonical: "
            "`OSRoundUp32B(x)` = `(x + 0x1F) & 0xFFFFFFE0` -> "
            "`rlwinm rD, rS, 0, 0, 26`."
        ),
        root_cause=(
            "`rlwinm` with shift=0 and mask covering high bits is a single-"
            "instruction wide-mask AND. `andi.` is limited to 16-bit "
            "immediates, so `& 0xFFFFFFE0` (wider) requires `rlwinm`."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi", "rlwinm"]},
                description="addi by alignment-1 + rlwinm clearing low bits",
            ),
        ],
        examples=[
            Example(
                function="lbmemory align-up",
                after=(
                    "// 32-byte alignment:\n"
                    "size_t aligned = (size + 0x1F) & ~0x1F;  // or & 0xFFFFFFE0\n"
                    "// -> addi r3, r3, 0x1F\n"
                    "//    rlwinm r3, r3, 0, 0, 26\n"
                ),
            ),
            Example(
                function="OSRoundUp32B(x)",
                after=(
                    "// From dolphin/os.h - canonical form:\n"
                    "#define OSRoundUp32B(x) (((u32)(x) + 0x1F) & ~0x1F)\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `(x + (A-1)) & ~(A-1)` for power-of-2 align-up. "
                    "MWCC fuses to addi+rlwinm. Don't try ifs or other forms."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["rlwinm", "addi"],
        categories=["data-layout", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="lbmemory alignment"),
                ProvenanceEntry(function="lbmthp alignment"),
            ],
        ),
    ),
    Pattern(
        id="bit-clear-low-bits-rlwinm-not-andi",
        name="`x & ~K` for K wider than 16 bits -> `rlwinm`, not `andi.`",
        description=(
            "`andi.` is a 16-bit immediate AND. Wide masks like `0xFFFFFFE0` "
            "exceed 16 bits, so MWCC uses `rlwinm` with shift=0 and a "
            "rotated mask. Example: `x & 0xFFFFFFE0` -> "
            "`rlwinm rD, rS, 0, 0, 26`."
        ),
        root_cause=(
            "PPC `andi.` instruction encodes only 16 bits of mask. For "
            "wider masks, MWCC uses `rlwinm` (rotate-then-mask) which can "
            "express any bit-pattern mask via (MB, ME) bit-range."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "rlwinm", "actual": "andi."},
                description="rlwinm for wide mask vs andi for <=16 bit mask",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// Wide masks - rlwinm:\n"
                    "x & 0xFFFFFFE0;  // rlwinm rD, rS, 0, 0, 26\n"
                    "x & 0xFFFFFFF0;  // rlwinm rD, rS, 0, 0, 27\n"
                    "x & 0xFFFF0000;  // rlwinm rD, rS, 0, 0, 15\n"
                    "\n"
                    "// Narrow masks - andi.:\n"
                    "x & 0xFF;        // andi. rD, rS, 0xFF\n"
                    "x & 0x7;         // andi. rD, rS, 0x7\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses rlwinm for an AND, the mask is wider "
                    "than 16 bits. When it uses andi., the mask fits in "
                    "16 bits."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["rlwinm", "andi."],
        categories=["type", "bitfield"],
        provenance=Provenance(),
    ),
    Pattern(
        id="byte-extract-shift-mask-rlwinm",
        name="`(x >> N) & 0xFF` byte extract -> single `rlwinm`",
        description=(
            "Extracting an aligned byte from a packed u32 via "
            "`(val >> 16) & 0xFF` fuses to a single "
            "`rlwinm rD, rS, ROT, 24, 31` (rotate-right N then mask byte). "
            "MWCC always fuses shift+mask into one rlwinm when both fit."
        ),
        root_cause=(
            "`rlwinm rD, rS, ROT, MB, ME` can express any (rotate, mask) "
            "combination in one instruction. MWCC's optimizer detects "
            "`(shift) & (mask)` patterns and emits rlwinm."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["rlwinm"]},
                description="Single rlwinm for shift+mask combo",
            ),
            Signal(
                type="opcode_mismatch",
                data={"expected": "rlwinm", "actual": "srwi+andi."},
                description="Fused rlwinm vs separate shift and mask",
            ),
        ],
        examples=[
            Example(
                function="eflib.c color extraction",
                after=(
                    "// Extract bytes from packed u32 RGBA:\n"
                    "u8 r = (col >> 24) & 0xFF;  // rlwinm r, col, 8, 24, 31\n"
                    "u8 g = (col >> 16) & 0xFF;  // rlwinm r, col, 16, 24, 31\n"
                    "u8 b = (col >> 8)  & 0xFF;  // rlwinm r, col, 24, 24, 31\n"
                    "u8 a = col & 0xFF;          // clrlwi r, col, 24\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Use `(x >> N) & MASK` for byte/field extraction. "
                    "Don't split into `tmp = x >> N; result = tmp & MASK;` "
                    "— that may emit two instructions."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["rlwinm", "srwi", "andi."],
        categories=["bitfield", "type"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="eflib color extraction"),
            ],
        ),
    ),
    Pattern(
        id="cntlzw-branchless-is-zero",
        name="`bool result = (x == 0)` -> `cntlzw + srwi 5` (branchless)",
        description=(
            "Assigning `(x == 0)` to a bool emits `cntlzw r0, rX` + "
            "`srwi r0, r0, 5`. cntlzw of 0 is 32 (high bit of result is 1); "
            "shifting right 5 gives 1. For non-zero x, cntlzw is <32, shifted "
            "right 5 gives 0. Branchless. NOT `cmpwi + branch + li`."
        ),
        root_cause=(
            "MWCC recognizes `(x == 0)` -> bool as a special pattern and "
            "emits the branchless trick. Other bool conversions may use "
            "the branch form."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cntlzw", "srwi"]},
                description="Count-leading-zeros + shift for bool conversion",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "bool is_zero(u32 x)\n"
                    "{\n"
                    "    return x == 0;\n"
                    "    // emits: cntlzw r0, r3 ; srwi r3, r0, 5 ; blr\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows `cntlzw + srwi 5` and you have a "
                    "branch+li, rewrite as `return x == 0;` directly. The "
                    "explicit `if (x == 0) return true; else return false;` "
                    "form emits the branch version instead."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cntlzw", "srwi"],
        categories=["branch", "type"],
        provenance=Provenance(),
        related_patterns=["static-inline-bool-explicit-true-false-return"],
    ),
    Pattern(
        id="divmod-fused-power-of-two-rlwinm",
        name="`/ N` and `% N` for power-of-2 N -> `srwi`+`rlwinm`",
        description=(
            "For `N` a power of 2, `x / N` becomes `srwi rD, rS, log2(N)` "
            "and `x % N` becomes `rlwinm rD, rS, 0, 32-log2(N), 31` "
            "(clear high bits). Combined patterns like "
            "`thing[i / 32] |= (1 << (i % 32))` fuse cleanly. Don't manually "
            "convert to shift/mask unless asm shows separate ops."
        ),
        root_cause=(
            "MWCC strength-reduces div/mod by power-of-2 constants to "
            "shifts/masks. Manual `>> 5` and `& 31` produce the same asm "
            "but `/ 32` and `% 32` are more readable."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["srwi", "rlwinm", "slw"]},
                description="Shift + mask + shift-by-register for bit-array indexing",
            ),
        ],
        examples=[
            Example(
                function="gmmain_lib.c bit array",
                after=(
                    "// Bit array indexing - all-shifts codegen:\n"
                    "thing[arg0 / 32] |= (1 << (arg0 % 32));\n"
                    "// Generates: srwi index, arg0, 5\n"
                    "//            rlwinm bit_pos, arg0, 0, 27, 31  (= & 31)\n"
                    "//            slw mask, one, bit_pos\n"
                    "//            ... OR and store\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Leave `/ N` and `% N` for power-of-2 N as division/"
                    "modulo in source. MWCC handles the strength reduction. "
                    "Only convert to explicit `>> ` and `& ` if the asm "
                    "shows divw/mullw being avoided in a non-obvious way."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["srwi", "rlwinm", "slw"],
        categories=["bitfield", "loop"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="gmmain_lib bit array"),
            ],
        ),
    ),
    Pattern(
        id="srawi-signed-shift-right",
        name="`(s32) x >> N` -> `srawi` (arithmetic right shift)",
        description=(
            "Signed right shift (`(s32) x >> N`) emits `srawi rD, rS, N`, "
            "which sign-extends as it shifts. Unsigned shift `(u32) x >> N` "
            "emits `srwi rD, rS, N` (zero-extends). Used for signed division "
            "by power of 2 (`x / 2^N` for signed x)."
        ),
        root_cause=(
            "PPC has separate signed (srawi) and unsigned (srwi) right-shift "
            "instructions to preserve C's signedness semantics. MWCC picks "
            "based on the operand's signed type."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "srawi", "actual": "srwi"},
                description="Arithmetic vs logical right shift",
            ),
        ],
        examples=[
            Example(
                function="it_2725.c hit data extraction",
                after=(
                    "// Sign-extending right shift:\n"
                    "value = ((s32) ((u32) cmd->u[0] << 15) & 0xFF800000) >> 24;\n"
                    "// emits: slwi + rlwinm + srawi (final arithmetic shift)\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses `srawi`, the C operand must be signed "
                    "(`s32`/`int`). Cast with `(s32)` if the source variable "
                    "is `u32`. When target uses `srwi`, the operand is unsigned."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["srawi", "srwi"],
        categories=["type", "bitfield"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="it_2725 hit extraction"),
            ],
        ),
    ),
    Pattern(
        id="extsh-extsb-sign-extension-placement",
        name="`extsh`/`extsb` for s16/s8 widening — cast through unsigned to suppress",
        description=(
            "When using an `s16` or `s8` value as `s32` in arithmetic, MWCC "
            "inserts `extsh` (halfword) or `extsb` (byte) for sign extension. "
            "Casting through a wider unsigned type suppresses the extension. "
            "If asm shows `extsh/extsb`, source must be signed-narrow."
        ),
        root_cause=(
            "PPC arithmetic on word-sized values requires explicit sign "
            "extension from narrower signed types. MWCC inserts extsh/extsb "
            "to materialize the signed value before use."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "extsh", "actual": "<missing>"},
                description="Sign extension expected but your code skipped it",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// s16 - emits extsh on use:\n"
                    "s16 x = ...;\n"
                    "foo(x);  // mr r3, x ; extsh r3, r3 ; bl foo\n"
                ),
                after=(
                    "// (u16) cast - no extsh, just clrlwi:\n"
                    "u16 x = ...;\n"
                    "foo(x);  // clrlwi r3, x, 16 ; bl foo\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target has `extsh`/`extsb`, the source variable is "
                    "`s16`/`s8` used in s32 context. If target has `clrlwi` "
                    "(zero-extension), it's `u16`/`u8`. Cast accordingly."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["extsh", "extsb", "clrlwi"],
        categories=["type"],
        provenance=Provenance(),
        related_patterns=["u8-parameter-mask-clrlwi", "clrlwi-between-u8-function-calls"],
    ),
    Pattern(
        id="rlwimi-bitfield-insert-vs-or-mask",
        name="Bitfield writes emit `rlwimi`; manual `& ~MASK | (val << N)` may emit separate ops",
        description=(
            "Writing to a struct bitfield (`s->b3 = 1;`) compiles to a single "
            "`rlwimi rD, rS, SH, MB, ME` (rotate-and-insert). Manually doing "
            "`flags = (flags & ~MASK) | (val << SHIFT);` may emit "
            "`rlwinm + or` (two instructions). Sysdolphin/HSD code prefers "
            "manual masks; fighter code prefers bitfields."
        ),
        root_cause=(
            "`rlwimi` inserts a bit-field from rS into rD without affecting "
            "other bits of rD. C bitfield writes compile directly to this. "
            "Manual mask-and-or doesn't always recognize the pattern."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "rlwimi", "actual": "rlwinm+or"},
                description="Bitfield insert vs manual mask+or",
            ),
        ],
        examples=[
            Example(
                function="fighter code (bitfield style)",
                after=(
                    "// Bitfield - single rlwimi:\n"
                    "fp->x221E_b5 = 1;  // rlwimi r,r,SH,MB,ME\n"
                ),
                before=(
                    "// Manual mask - rlwinm + or:\n"
                    "fp->x221E = (fp->x221E & ~0x04) | (1 << 2);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `rlwimi`, use C bitfield syntax in your "
                    "struct: `T b3 : 1;` and `s->b3 = val;`. When target has "
                    "`rlwinm + or`, use manual mask-and-or with full-word "
                    "operations."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["rlwimi", "rlwinm", "or"],
        categories=["bitfield"],
        provenance=Provenance(),
        related_patterns=[
            "bitfield-assignment-vs-explicit-bit-manipulation",
            "bitfield-packing",
        ],
    ),
    Pattern(
        id="bool-via-cmpwi-cror-mfcr-shift",
        name="Multi-condition bool emits `cmpwi`+`cror`+`mfcr`+`rlwinm`",
        description=(
            "Booleans from multi-condition tests (`bool ok = (a && b);`) "
            "compile to `cmpwi` for each test, `cror` to combine condition "
            "register bits, `mfcr` to extract to GPR, and `rlwinm` to "
            "isolate the result bit. Different shift counts (0x1F, 0x1E, "
            "0x1D) correspond to different operators (LT/GT/EQ)."
        ),
        root_cause=(
            "PPC's condition register has 4 bits per `cmp` result (lt, gt, "
            "eq, un). Boolean combinations operate at the CR level, then "
            "extract to GPR. MWCC picks the cror operation matching the C "
            "boolean operator."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmpwi", "cror", "mfcr", "rlwinm"]},
                description="Multi-condition bool extraction sequence",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "bool both_set(int a, int b)\n"
                    "{\n"
                    "    return (a != 0) && (b != 0);\n"
                    "    // cmpwi cr0, r3, 0\n"
                    "    // cmpwi cr1, r4, 0\n"
                    "    // cror eq, cr0_eq, cr1_eq (combine)\n"
                    "    // mfcr r3\n"
                    "    // rlwinm r3, r3, 3, 31, 31\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target shows the cmpwi-cror-mfcr-rlwinm sequence "
                    "for a bool, the source is a compound boolean expression. "
                    "Don't try to factor into separate ifs."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["cmpwi", "cror", "mfcr", "rlwinm"],
        categories=["branch", "bitfield"],
        provenance=Provenance(),
    ),
    Pattern(
        id="power-of-2-multiply-as-slwi",
        name="`x * N` for power-of-2 N always emits `slwi` (left shift), not `mulli`",
        description=(
            "MWCC strength-reduces multiplies by power-of-2 constants to "
            "`slwi rD, rS, log2(N)` (or `rlwinm`). Always — never falls back "
            "to `mulli` for power-of-2 constants. Conversely, non-power-of-2 "
            "like `x * 60` keeps `mulli`. Use `* 8` or `<< 3` "
            "interchangeably; codegen is identical."
        ),
        root_cause=(
            "Multiply by power-of-2 is exactly a left shift. Strength "
            "reduction is unconditional in MWCC."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "slwi", "actual": "mulli"},
                description="Shift for power-of-2 multiplier vs multiply",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// Same codegen:\n"
                    "x * 8;       // slwi rD, rS, 3\n"
                    "x << 3;      // slwi rD, rS, 3\n"
                    "// Different codegen:\n"
                    "x * 60;      // mulli rD, rS, 60\n"
                    "x * 16;      // slwi rD, rS, 4\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses `slwi`, the multiplier is a power of 2. "
                    "Source can use either `* N` or `<< log2(N)` - identical "
                    "codegen. Prefer `* N` for stride-style arithmetic."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["slwi", "mulli"],
        categories=["type", "bitfield"],
        provenance=Provenance(),
    ),
    # ---- string / memory ops ----
    Pattern(
        id="memset-emits-bl-not-inline",
        name="`memset(p, 0, N)` always emits `bl memset` — never inlined",
        description=(
            "MWCC does NOT inline `memset` even for small constant N. It "
            "always emits `bl memset`. If your code has inline `stw 0` "
            "runs but the target has `bl memset`, fold to `memset(p, 0, "
            "sizeof(T))`. The fill byte and count land in r4 and r5 as "
            "immediates."
        ),
        root_cause=(
            "MWCC's MSL `memset` is not declared `static inline` and the "
            "compiler doesn't have a builtin path for it. Every call site "
            "goes through the library function."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl memset", "actual": "stw r0,0(rN); stw r0,4(rN); ..."},
                description="Library call vs inline zero stores",
            ),
        ],
        examples=[
            Example(
                function="lbarchive.c struct zero",
                after=(
                    "memset(archive, 0, sizeof(HSD_Archive));\n"
                    "// addi r3, archive_ptr\n"
                    "// li r4, 0\n"
                    "// li r5, sizeof(HSD_Archive)\n"
                    "// bl memset\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `bl memset` with a constant size, use "
                    "`memset(p, 0, sizeof(T))` in source. Don't write "
                    "manual zero loops or aggregate `{0}` init for heap-"
                    "allocated structs."
                ),
                success_rate=0.95,
            ),
            Fix(
                description=(
                    "For STACK locals, `T x = {0};` emits inline stw zeros "
                    "instead of `bl memset`. See "
                    "`zero-init-aggregate-stack-fill` pattern."
                ),
            ),
        ],
        opcodes=["bl"],
        categories=["calling-conv", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="HSD_Archive init"),
            ],
        ),
    ),
    Pattern(
        id="memset-sizeof-difference-skip-prefix",
        name="`memset(&s->field, 0, sizeof(T) - sizeof(prefix))` to skip a leading region",
        description=(
            "When init zeroes most of a struct but skips a leading field "
            "(like vmtx), the size is expressed as "
            "`sizeof(StructT) - sizeof(SkippedT)`. Constant-folded at "
            "compile time; lands as an immediate in r5."
        ),
        root_cause=(
            "C's compile-time sizeof arithmetic produces a constant. MWCC "
            "folds it to a single immediate for the memset count argument. "
            "The struct is offset by the skipped prefix's size."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["addi", "li", "li", "bl memset"]},
                description="Address-of-field + zero + odd size + memset",
            ),
        ],
        examples=[
            Example(
                function="displayfunc.c HSD_ZList partial init",
                after=(
                    "// Skip leading vmtx field, zero the rest:\n"
                    "memset(&list->vmtx, 0, sizeof(HSD_ZList) - sizeof(Mtx));\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target's memset count is an 'odd' size that doesn't "
                    "match any single struct, check if it's "
                    "`sizeof(T) - sizeof(SkippedT)`. The source likely "
                    "skips a leading struct field."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["bl", "li"],
        categories=["struct", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="displayfunc HSD_ZList init"),
            ],
        ),
    ),
    Pattern(
        id="memset-fill-byte-0xff-sentinel",
        name="`memset(p, 0xFF, ...)` for all-bits-set sentinel init",
        description=(
            "Some HSD types initialize to all-bits-set (e.g., HSD_TETev). "
            "Generates `li r4, 0xFF` (or 255) before `bl memset`. Don't "
            "write a manual loop; use `memset` with explicit fill byte."
        ),
        root_cause=(
            "All-bits-set sentinel values (-1 for signed, 0xFFFFFFFF for "
            "unsigned) need each byte initialized to 0xFF. The fill-byte "
            "argument lands in r4."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["li r4,0xFF", "bl memset"]},
                description="memset with 0xFF fill byte",
            ),
        ],
        examples=[
            Example(
                function="texp.c HSD_TETev init",
                after=(
                    "memset(texp, 0xFF, sizeof(HSD_TETev));\n"
                    "// li r4, 0xFF\n"
                    "// li r5, sizeof(HSD_TETev)\n"
                    "// bl memset\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has `li r4, 0xFF` before `bl memset`, source "
                    "uses `memset(p, 0xFF, sizeof(T))`. Don't write a manual "
                    "byte-set loop."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["bl", "li"],
        categories=["calling-conv", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="HSD_TETev init"),
            ],
        ),
    ),
    Pattern(
        id="memcpy-explicit-vs-struct-assignment-codegen",
        name="`memcpy(...)` vs `*dst = *src` produce different codegen (`bl memcpy` vs `bl __memcpy`)",
        description=(
            "Explicit `memcpy(dst, src, sizeof(T))` emits `bl memcpy` "
            "(relocation to memcpy symbol). Struct assignment `*dst = *src` "
            "emits either inline `lwz`/`stw` runs OR `bl __memcpy` (the "
            "compiler-internal intrinsic). Pick based on which the target uses."
        ),
        root_cause=(
            "MWCC has two paths: explicit memcpy calls go through MSL's "
            "`memcpy`. Implicit struct-copy via assignment uses an internal "
            "`__memcpy` (sometimes inlined). The relocation symbol name "
            "differs: `memcpy` vs `__memcpy`."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl memcpy", "actual": "bl __memcpy"},
                description="Library memcpy vs intrinsic __memcpy",
            ),
        ],
        examples=[
            Example(
                function="HSD_Archive copy",
                before=(
                    "// Explicit - bl memcpy:\n"
                    "memcpy(archive, src, sizeof(HSD_ArchiveHeader));\n"
                ),
                after=(
                    "// Struct assignment - bl __memcpy (or inline):\n"
                    "*archive = *src;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target relocs against `memcpy`, use explicit "
                    "`memcpy(...)`. If target relocs against `__memcpy` "
                    "(double underscore), use struct assignment `*dst = *src`."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["bl"],
        categories=["calling-conv", "struct"],
        provenance=Provenance(),
        related_patterns=["copying-structs-field-by-field", "memcpy-sizeof-array-type"],
    ),
    Pattern(
        id="strcpy-not-inlined-emits-bl",
        name="`strcpy` is never inlined — always `bl strcpy`",
        description=(
            "MWCC does not inline `strcpy`, even for small string literals "
            "with known length. Always emits `bl strcpy` with the dest "
            "pointer in r3 and source in r4. Don't try to replace with "
            "`memcpy` or manual byte loop for matching."
        ),
        root_cause=(
            "Same as memset: strcpy is not in MWCC's intrinsic builtin path "
            "in 1.2.5n. Every call goes through MSL's library function."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl strcpy", "actual": "<other>"},
                description="strcpy library call expected",
            ),
        ],
        examples=[
            Example(
                function="lbaudio_ax string init",
                after=(
                    "strcpy(lbl_803BB340, \"/audio/us/\");\n"
                    "// lis r4, @ha(str_literal)\n"
                    "// addi r4, r4, @l(str_literal)\n"
                    "// bl strcpy\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Always use `strcpy(dst, src_literal)` for string init. "
                    "Don't use `memcpy(dst, src_literal, sizeof(src_literal))` "
                    "as a substitute — it emits `bl memcpy`, different reloc."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=["bl"],
        categories=["calling-conv", "data-layout"],
        provenance=Provenance(),
    ),
    Pattern(
        id="zero-init-aggregate-stack-fill",
        name="`T x = {0};` for stack local emits inline `stw 0` runs (no `bl memset`)",
        description=(
            "Zero-initializing a stack-local struct or array via `T x = "
            "{0};` emits inline `li r0, 0; stw r0, OFFSET(r1)` runs to "
            "zero the stack region. f64 fields get `stfd` from a zero "
            "fp register. NOT `bl memset` — that path is for heap or "
            "explicit memset calls."
        ),
        root_cause=(
            "MWCC initializes stack aggregates with direct stores. The "
            "compiler knows the stack offsets at compile time and emits "
            "unrolled zero-stores. For larger arrays (>some threshold), "
            "it may fall back to a loop or memset call."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["li r0,0", "stw r0,N1(r1)", "stw r0,N2(r1)"]},
                description="Unrolled zero stores to stack",
            ),
        ],
        examples=[
            Example(
                function="ftbosslib.c, ftcliffcommon.c",
                after=(
                    "// Stack-local zero init:\n"
                    "Quaternion quat = { 0 };\n"
                    "u8 _[16] = { 0 };\n"
                    "// Emits sequence of `li r0,0; stw r0, OFFSET(r1)`\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "For stack-local aggregates, use `T x = {0};` "
                    "initialization. Emits inline `stw 0` runs without a "
                    "memset call. For heap or non-init paths, use "
                    "`memset(&x, 0, sizeof(x))`."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=["li", "stw", "stfd"],
        categories=["stack", "data-layout"],
        provenance=Provenance(
            discovered_from=[
                ProvenanceEntry(function="Quaternion stack init"),
            ],
        ),
        related_patterns=["memset-emits-bl-not-inline", "static-inline-stack-dummy-array"],
    ),
]


def main():
    db_path = DEFAULT_DB_PATH
    conn = init_db(db_path)
    db = PatternDB(conn)

    inserted = 0
    updated = 0

    for pattern in PATTERNS:
        existing = db.get(pattern.id)
        if existing is not None:
            print(f"  EXISTS: {pattern.id} — deleting and re-inserting")
            conn.execute("DELETE FROM patterns WHERE id = ?", (pattern.id,))
            conn.execute("DELETE FROM pattern_signals WHERE pattern_id = ?", (pattern.id,))
            conn.commit()
            db.insert(pattern)
            updated += 1
        else:
            db.insert(pattern)
            print(f"  ADDED:  {pattern.id}")
            inserted += 1

    print()
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Total patterns in DB now: {len(db.list_all())}")


if __name__ == "__main__":
    main()
